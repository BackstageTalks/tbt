"""Read-only point-model replay. Target match results never enter a prediction."""
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from heapq import heappop, heappush
from math import exp, isfinite, log
from numbers import Real

from ..data.court_speed import _match_speed_raw, court_speed_venue_key
from ..match_format import explicit_best_of_from_event, infer_best_of
from .elo import elo_expected, update_elo
from .feature_builder import stats_surface_key
from .point_rules import rules_for, calibration_level
from .point_simulation import elo_shift, game, simulate

UTC = timezone.utc
DAY = timedelta(days=1)
HALF_LIFE = 120
LOOKBACK = 540
DEFAULT = {"atp": .62, "wta": .57}
RATE_FIELDS = (
    "service_points_won", "return_points_won", "first_serve_in",
    "break_point_serve_win", "break_point_return_win", "aces", "double_faults",
)
MISSING = "--"


def competition(match):
    level = match.tournament_level.lower()
    if "itf" in level:
        return "ITF"
    if "challenger" in level:
        return "Challenger"
    if "utr" in level:
        return "UTR"
    if level == "wta 125":
        return "WTA 125"
    return match.tour.upper() if not level or match.tour in ("atp", "wta") else "Other"


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return result.astimezone(UTC) if result.tzinfo else None


def _usable_result(match):
    raw = match.provider_payload or {}
    return (match.is_completed and match.player1_id != match.player2_id
            and match.status.lower() in {"finished", "completed", "ended", "ft", "final"}
            and not raw.get("_tbt_termination")
            and "double" not in f"{match.tour} {match.tournament_level}".lower())


def _ready_times(match):
    # Legacy canonical results have a scheduled clock but often no finish clock.
    # Leave one complete UTC day for finishing before using such records.
    start = match.scheduled_at.astimezone(UTC)
    raw = match.provider_payload or {}
    finish = timestamp(raw.get("completed_at") or raw.get("finished_at"))
    result_ready = max(start, finish) if finish else start.replace(hour=0, minute=0, second=0, microsecond=0) + 2 * DAY
    stats_ready = result_ready
    for field, clock in (("_tbt_statistics", "fetched_at"), ("_tbt_score", "fetched_at")):
        marker = raw.get(field)
        if isinstance(marker, dict) and marker.get(clock):
            observed = timestamp(marker[clock])
            if observed is None:
                return result_ready, None
            stats_ready = max(stats_ready, observed)
    return result_ready, stats_ready


def _number(value, maximum):
    return (float(value) if isinstance(value, Real) and not isinstance(value, bool)
            and isfinite(value) and 0 <= value <= maximum else None)


def _observations(stats, player):
    side, other = f"p{player}", f"p{3 - player}"
    own_games = _number(stats.get(f"{side}_games_won"), 100)
    other_games = _number(stats.get(f"{other}_games_won"), 100)
    points = _number(stats.get(f"{side}_service_points_total"), 400)
    if not points and own_games is not None and other_games is not None and own_games + other_games >= 12:
        # Exposure proxy for count-only matches, including legacy canonical rows.
        service_rate = _number(stats.get(f"{side}_service_points_won"), 1)
        points = (own_games + other_games) / 2 * game(.6 if service_rate is None else service_rate)[1]
    values = [_number(stats.get(f"{side}_{field}"), 1) for field in RATE_FIELDS[:5]]
    if values[0] is None:
        complement = _number(stats.get(f"{other}_return_points_won"), 1)
        values[0] = None if complement is None else 1 - complement
    if values[1] is None:
        complement = _number(stats.get(f"{other}_service_points_won"), 1)
        values[1] = None if complement is None else 1 - complement
    for field in RATE_FIELDS[5:]:
        count = _number(stats.get(f"{side}_{field}"), 100)
        values.append(count / points if points and count is not None and count <= points else None)
    return tuple(values), points


def _logit(p):
    p = min(.99, max(.01, p))
    return log(p / (1 - p))


def _probability(x):
    return 1 / (1 + exp(-x))


def format_for(match):
    raw = match.provider_payload or {}
    best, source = infer_best_of(
        explicit=explicit_best_of_from_event(raw),
        tour=match.tour, tournament=match.tournament,
        tournament_level=match.tournament_level, round_name=match.round_name,
    )
    if "next gen" in match.tournament.lower() and "final" in match.tournament.lower():
        return 5, 7, "next_gen_rules"
    if any(token in f" {match.tournament} {match.tournament_level} {match.tour} ".lower()
           for token in ("next gen", "fast4", "wheelchair", "doubles", "exhibition")):
        return None, 7, "unsupported_format"
    name = f"{match.tournament} {match.tournament_level}".lower()
    slam = any(token in name for token in ("grand slam", "australian open", "roland garros",
                                            "french open", "wimbledon", "us open", "u.s. open"))
    target = raw.get("deciding_tiebreak", 10 if slam else 7)
    return best, target, source


def section(value, matches):
    return {"value": value if value is not None else MISSING, "matches": matches}


class PointHistory:
    def __init__(self, matches):
        self.results, self.statistics, self.starts = [], [], []
        self.pre_match_elo = {}
        self.players = defaultdict(lambda: deque(maxlen=100))
        self.elo = {}
        self.form = defaultdict(lambda: deque(maxlen=10))
        self.h2h = defaultdict(lambda: defaultdict(int))
        self.priors = defaultdict(lambda: [0., 0., 0])
        self.prior_clock = {}
        self.speed = defaultdict(lambda: [0., 0])
        self.cutoff = datetime.min.replace(tzinfo=UTC)
        for index, match in enumerate(matches):
            if not _usable_result(match):
                continue
            result, stats = _ready_times(match)
            heappush(self.results, (result, index, match))
            heappush(self.starts, (match.scheduled_at, index, match))
            if stats and match.stats:
                heappush(self.statistics, (stats, index, match))

    def advance(self, cutoff):
        if cutoff.tzinfo is None or cutoff < self.cutoff:
            raise ValueError("Replay clock must be timezone-aware and monotonic")
        self.cutoff = cutoff
        while self.starts or self.results:
            starts = self.starts and (not self.results or self.starts[0][0] <= self.results[0][0])
            queue = self.starts if starts else self.results
            if queue[0][0] >= cutoff:
                break
            _, index, match = heappop(queue)
            if starts:
                self.pre_match_elo[index] = self.elo_probability(match)[0]
            else:
                self._result(match, self.pre_match_elo.pop(index))
        while self.statistics and self.statistics[0][0] < cutoff:
            _, _, match = heappop(self.statistics)
            self._statistics(match)

    def _result(self, match, elo_p):
        surface = stats_surface_key(match.surface)
        left, right = match.player1_id, match.player2_id
        won = float(match.winner_id == left)
        for player, error in ((left, won - elo_p), (right, elo_p - won)):
            self.form[match.tour, player].append((match.scheduled_at, error))
        for scope in ("", surface):
            keys = ((match.tour, left, scope), (match.tour, right, scope))
            (a, n1), (b, n2) = (self.elo.get(key, (1500., 0)) for key in keys)
            a, b = update_elo(a, b, won, n1, n2)
            self.elo[keys[0]], self.elo[keys[1]] = (a, n1 + 1), (b, n2 + 1)
        self.h2h[match.tour, *sorted((left, right))][match.winner_id] += 1

    def elo_probability(self, match):
        surface = stats_surface_key(match.surface)
        a, b = [], []
        for player in (match.player1_id, match.player2_id):
            overall, n = self.elo.get((match.tour, player, ""), (1500., 0))
            specific, ns = self.elo.get((match.tour, player, surface), (1500., 0))
            weight = .65 * ns / (ns + 12)
            a.append(overall + weight * (specific - overall))
            b.append(n)
        return elo_expected(*a), b

    def _statistics(self, match):
        age = (self.cutoff - match.scheduled_at).total_seconds() / 86400
        if age > LOOKBACK:
            return
        surface = stats_surface_key(match.surface)
        level = competition(match)
        serves = []
        for side, pid in enumerate((match.player1_id, match.player2_id), 1):
            values, points = _observations(match.stats, side)
            if not any(value is not None for value in values):
                continue
            self.players[match.tour, pid].append((match.scheduled_at, surface, level, values, points))
            if values[0] is not None and .25 <= values[0] <= .95:
                serves.append(values[0])
        if serves:
            w = 2 ** (-age / HALF_LIFE)
            for key in ((match.tour, level, surface), (match.tour, level, ""), (match.tour, "", "")):
                total, weight, count = self.priors[key]
                # Rebase at every update to keep exponentials small.
                old_at = self.prior_clock.get(key, self.cutoff)
                decay = 2 ** (-(self.cutoff - old_at).total_seconds() / (86400 * HALF_LIFE))
                self.priors[key] = [
                    total * decay + w * sum(serves) / len(serves), weight * decay + w, count + 1]
                self.prior_clock[key] = self.cutoff
        raw_speed = _match_speed_raw(match)
        if raw_speed is not None:
            key = court_speed_venue_key(match.tour, match.tournament, match.surface)
            for bucket in ((match.tour, surface), key):
                if bucket:
                    row = self.speed[bucket]
                    row[0] += raw_speed
                    row[1] += 1

    def _baseline(self, tour, level, surface):
        prior = DEFAULT.get(tour, .60)
        samples = 0
        for key in ((tour, "", ""), (tour, level, ""), (tour, level, surface)):
            total, weight, count = self.priors.get(key, (0., 0., 0))
            age = (self.cutoff - self.prior_clock.get(key, self.cutoff)).total_seconds() / 86400
            decay = 2 ** (-age / HALF_LIFE)
            prior = (total * decay + 25 * prior) / (weight * decay + 25)
            samples = count or samples
        return min(.75, max(.48, prior)), samples

    def _profile(self, match, player, level, surface, baseline):
        totals, weights, counts = [0.] * 7, [0.] * 7, [0] * 7
        primary = 0
        for played, court, tier, values, points in self.players.get((match.tour, player), ()):
            age = (self.cutoff - played).total_seconds() / 86400
            if age > LOOKBACK:
                continue
            w = 2 ** (-age / HALF_LIFE) * (1 if court == surface else .45) * (1 if tier == level else .65)
            w *= min(1.5, max(.5, (points or 60) / 60))
            primary += int(values[0] is not None or values[1] is not None)
            for i, value in enumerate(values):
                if value is not None:
                    totals[i] += w * value
                    weights[i] += w
                    counts[i] += 1
        priors = (baseline, 1 - baseline, .60, baseline, 1 - baseline, .055, .045)
        rates = [(totals[i] + 5 * prior) / (weights[i] + 5) if counts[i] else None
                 for i, prior in enumerate(priors)]
        return rates, counts, primary

    def card(self, match, opponent_styles=None, *, candidate=None, offsets=None):
        if match.scheduled_at.tzinfo is None or self.cutoff >= match.scheduled_at:
            raise ValueError("History cutoff must precede match start")
        best, deciding, format_source = format_for(match)
        rules = rules_for(match)
        if rules is None or best not in (3, 5) or deciding not in (7, 10):
            return None
        ids = match.player1_id, match.player2_id
        level, surface = competition(match), stats_surface_key(match.surface)
        prior, prior_n = self._baseline(match.tour, level, surface)
        elo, elo_counts = self.elo_probability(match)
        left, right = (self._profile(match, pid, level, surface, prior) for pid in ids)
        rates, counts = (left[0], right[0]), (left[1], right[1])
        primary_counts = [left[2], right[2]]
        fallback = any(value is None for row in rates for value in row[:2])
        quality = "elo_fallback" if fallback else "low" if min(counts[0][:2] + counts[1][:2]) < 8 else "supported"
        if fallback:
            shift = elo_shift(round(prior, 2), round(max(elo, 1 - elo), 3), best, deciding)
            shift *= 1 if elo >= .5 else -1
            base = round(prior, 2)
            point_rates = (base + shift, base - shift)
        else:
            point_rates = []
            for server, receiver in (rates, rates[::-1]):
                serve, ret = server[0], receiver[1]
                first, bp_serve, bp_return = server[2], server[3], receiver[4]
                # Log-odds multiplication of contextual serve and return strengths.
                # Secondary signals are centered and deliberately weak to limit double counting.
                adjustment = (.12 * ((first if first is not None else .60) - .60)
                              + .15 * ((bp_serve if bp_serve is not None else prior) - prior)
                              - .15 * ((bp_return if bp_return is not None else 1 - prior) - (1 - prior))
                              + .25 * ((server[5] if server[5] is not None else .055) - .055)
                              - .25 * ((server[6] if server[6] is not None else .045) - .045))
                point_rates.append(min(.90, max(.20, _probability(_logit(serve) - _logit(ret) - _logit(prior) + adjustment))))
        anchor = None
        if candidate is not None:
            from .point_anchor import CANDIDATE, anchored_rates, calibrated_mean
            tier = calibration_level(match)
            key = f"{tier}|{surface}"
            entry = offsets.get(key, offsets.get(tier, offsets["all"]))
            raw = tuple(point_rates)
            mean = calibrated_mean(sum(raw) / 2, entry["offset"])
            point_rates = anchored_rates(mean, candidate, best, deciding, rules)
            anchor = {"candidate": CANDIDATE, "probability": candidate,
                      "raw_service_mean": sum(raw) / 2, "service_mean": mean,
                      "calibration_n": entry["n"], "calibration_offset": entry["offset"]}
        prediction = simulate(*point_rates, best, deciding, rules)
        form = [[error for date, error in self.form.get((match.tour, pid), ())
                 if self.cutoff - date <= 180 * DAY] for pid in ids]
        h2h = self.h2h.get((match.tour, *sorted(ids)), {})
        speed_total, speed_n = self.speed.get(court_speed_venue_key(match.tour, match.tournament, match.surface), (0., 0))
        court_total, court_n = self.speed.get((match.tour, surface), (0., 0))
        speed = 100 * (speed_total / speed_n) / (court_total / court_n) if speed_n >= 5 and court_n >= 20 and court_total > 0 else None
        style = [self._style((opponent_styles or {}).get(pid)) for pid in reversed(ids)]
        win = prediction["winner"]
        evidence = {"point_matches_by_player": primary_counts, "elo_matches_by_player": elo_counts,
                    "competition_matches": prior_n}
        sample = elo_counts if fallback else primary_counts
        stats = [{"aces": section(r[5] * p if r[5] is not None else None, c[5]),
                  "double_faults": section(r[6] * p if r[6] is not None else None, c[6]),
                  "breaks": section(b, sample[i])}
                 for i, (r, c, p, b) in enumerate(zip(rates, counts, prediction["service_points"], prediction["breaks"]))]
        return {
            "schema": 3 if anchor else 1, "anchor": anchor, "shadow": True, "match_id": match.match_id,
            "as_of": self.cutoff.isoformat(), "scheduled_at": match.scheduled_at.isoformat(),
            "scoring_rules": vars(rules), "players": ids, "competition": level, "best_of": best, "format_source": format_source,
            "deciding_tiebreak_to": 10 if rules.match_tiebreak else deciding, "data_quality": quality, "low_data": quality != "supported",
            "evidence": evidence,
            "favorite": section({"player_id": ids[int(win[1] > win[0])] if abs(win[0] - win[1]) > 1e-12 else MISSING,
                                 "probabilities": win}, sample),
            "set_score": section(prediction["set_score"], sample),
            "scenarios": section({k: prediction[k] for k in ("at_least_one_set", "first_set", "comeback_given_first_set_loss")}, sample),
            "exact_score": section({"match_top3": prediction["exact_match_top3"],
                                    "by_set": prediction["exact_sets"]}, sample),
            "serve_return": section([
                {"serve_point": point_rates[i], "return_point": 1 - point_rates[1 - i],
                 "history": {k: section(value, n) for k, value, n in zip(RATE_FIELDS, r, c)}}
                for i, (r, c) in enumerate(zip(rates, counts))], sample),
            "predicted_stats": section(stats, sample),
            "other_projections": section({k: prediction[k] for k in ("total_games", "game_margin_player1", "totals", "handicap", "tiebreak")}, sample),
            "form_vs_elo": section({"elo_probability": (elo, 1 - elo),
                                    "recent_win_rate_minus_expected": [sum(x) / len(x) if x else MISSING for x in form]},
                                   [len(x) for x in form]),
            "head_to_head": section([h2h.get(pid, 0) for pid in ids] if h2h else None, sum(h2h.values())),
            "opponent_style": section([item["value"] for item in style], [item["matches"] for item in style]),
            "court_speed": section(speed, speed_n),
        }

    def _style(self, profile):
        # External style artifact must carry its own point-in-time evidence.
        profile = profile if isinstance(profile, dict) else {}
        as_of = timestamp(profile.get("as_of"))
        matches = profile.get("matches")
        if as_of and as_of < self.cutoff and type(matches) is int and matches > 0 and profile.get("value"):
            return section(profile["value"], matches)
        return section(None, 0)
