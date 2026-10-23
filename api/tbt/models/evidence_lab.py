"""Opt-in, research-only point-in-time DIL evidence features and reliability gate.

No database writer, production selector integration, probability recalibration or
training side effects. Callers must supply independently reviewed canonical IDs
and a real source-availability timestamp; this layer never guesses links.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Iterable, Mapping


@dataclass(frozen=True)
class HistoricalEvidence:
    canonical_match_id: str
    tour: str
    player_id: str
    surface: str
    started_at: datetime
    completed_at: datetime
    available_at: datetime
    expected_recorded_at: datetime
    won: bool
    expected_win: float  # historical *pre-match* expected probability
    service_points: int | None = None
    first_in: int | None = None
    first_won: int | None = None
    second_won: int | None = None
    opponent_service_points: int | None = None
    opponent_first_won: int | None = None
    opponent_second_won: int | None = None
    bp_saved: int | None = None
    bp_faced: int | None = None
    opponent_bp_saved: int | None = None
    opponent_bp_faced: int | None = None
    reviewed_cdb_link: bool = False


def _aware(t: datetime) -> None:
    if not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("Timezone-aware timestamps are required")


def _rate(won: int | None, total: int | None) -> tuple[int, int] | None:
    if won is None or total is None:
        return None
    if isinstance(won, bool) or isinstance(total, bool) or not isinstance(won, int) or not isinstance(total, int):
        raise ValueError("Raw service / break-point counters must be integers")
    if total < 0 or won < 0 or won > total:
        raise ValueError("Inconsistent won/total counts")
    return (won, total) if total > 0 else None


def _sum_known(a: int | None, b: int | None) -> int | None:
    return a + b if a is not None and b is not None else None


def _second_attempts(r: HistoricalEvidence) -> int | None:
    if r.service_points is None or r.first_in is None:
        return None
    if r.first_in > r.service_points or r.first_in < 0:
        raise ValueError("Invalid first serve attempts")
    return r.service_points - r.first_in


def _validate_counts(r: HistoricalEvidence) -> None:
    """Validate even partial source counters; a missing denominator is not a waiver."""
    fields = (
        "service_points", "first_in", "first_won", "second_won",
        "opponent_service_points", "opponent_first_won", "opponent_second_won",
        "bp_saved", "bp_faced", "opponent_bp_saved", "opponent_bp_faced",
    )
    for key in fields:
        value = getattr(r, key)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("Invalid raw source counter: " + key)

    for numerator, denominator in (
        (r.first_in, r.service_points),
        (r.first_won, r.first_in),
        (r.first_won, r.service_points),
        (r.second_won, r.service_points),
        (r.bp_saved, r.bp_faced),
        (r.opponent_first_won, r.opponent_service_points),
        (r.opponent_second_won, r.opponent_service_points),
        (r.opponent_bp_saved, r.opponent_bp_faced),
    ):
        if numerator is not None and denominator is not None and numerator > denominator:
            raise ValueError("Impossible source count numerator / denominator")
    if r.first_in is not None and r.service_points is not None:
        second_attempts = r.service_points - r.first_in
        if r.second_won is not None and r.second_won > second_attempts:
            raise ValueError("Second-serve wins exceed second attempts")
    for total, first, second in (
        (r.service_points, r.first_won, r.second_won),
        (r.opponent_service_points, r.opponent_first_won, r.opponent_second_won),
    ):
        if None not in (total, first, second) and first + second > total:
            raise ValueError("Service points won exceed points played")


def _counts(r: HistoricalEvidence) -> dict[str, tuple[int, int] | None]:
    _validate_counts(r)
    serve_won = _sum_known(r.first_won, r.second_won)
    opp_won = _sum_known(r.opponent_first_won, r.opponent_second_won)
    if opp_won is not None and r.opponent_service_points is not None:
        ret_won = r.opponent_service_points - opp_won
    else:
        ret_won = None
    if r.bp_faced is not None and r.bp_saved is not None:
        _rate(r.bp_saved, r.bp_faced)
    if r.opponent_bp_faced is not None and r.opponent_bp_saved is not None:
        _rate(r.opponent_bp_saved, r.opponent_bp_faced)
    convert = (r.opponent_bp_faced - r.opponent_bp_saved
               if r.opponent_bp_faced is not None and r.opponent_bp_saved is not None else None)
    return {
        "serve": _rate(serve_won, r.service_points),
        "return": _rate(ret_won, r.opponent_service_points),
        "second_serve": _rate(r.second_won, _second_attempts(r)),
        "bp_save": _rate(r.bp_saved, r.bp_faced),
        "bp_convert": _rate(convert, r.opponent_bp_faced),
    }


def _surface(surface: str) -> str:
    s = str(surface or "unknown").strip().lower()
    return "hard" if s == "indoor_hard" else s


def player_features(records: Iterable[HistoricalEvidence], *, player_id: str, tour: str,
                    surface: str, issued_at: datetime, limit: int = 20) -> dict:
    """PIT features from at most 20 prior completed canonical matches.

    A date-only historical match must not inform another match on the same UTC
    day. Source availability is mandatory to rule out post-hoc enrichment.
    """
    _aware(issued_at)
    if tour.lower() not in {"atp", "wta"} or not player_id or limit < 1:
        raise ValueError("Explicit ATP/WTA canonical player and positive window required")
    prior: list[HistoricalEvidence] = []
    seen: set[str] = set()
    cutoff_day = issued_at.astimezone(timezone.utc).date()
    for r in records:
        if r.player_id != player_id or r.tour.lower() != tour.lower():
            continue
        if r.reviewed_cdb_link is not True or not r.canonical_match_id:
            raise ValueError("Unreviewed or missing canonical CDB identity")
        _aware(r.started_at)
        _aware(r.completed_at)
        _aware(r.available_at)
        _aware(r.expected_recorded_at)
        if (not isinstance(r.won, bool) or r.started_at > r.completed_at
                or r.expected_recorded_at >= r.started_at):
            raise ValueError("Prior probability must be verified before actual match start")
        if r.completed_at > r.available_at:
            raise ValueError("Source stats marked available before match completion")
        if r.completed_at.astimezone(timezone.utc).date() >= cutoff_day or r.available_at > issued_at:
            continue
        if r.canonical_match_id in seen:
            raise ValueError("Duplicate linked canonical match for a player")
        seen.add(r.canonical_match_id)
        if not math.isfinite(r.expected_win) or not 0 <= r.expected_win <= 1:
            raise ValueError("Missing verified pre-match opponent expectation")
        _counts(r)  # validate even if the row falls outside the recent window
        prior.append(r)
    prior.sort(key=lambda r: (r.completed_at, r.canonical_match_id), reverse=True)
    selected = prior[:limit]
    same = [r for r in selected if _surface(r.surface) == _surface(surface)
            and _surface(surface) != "unknown"]

    def residual(rows):
        weights = [0.5 ** ((issued_at - r.completed_at).total_seconds() / 86400 / 90)
                   for r in rows]
        return sum(w * (float(r.won) - r.expected_win) for r, w in zip(rows, weights)) / (6.0 + sum(weights))

    # Shrink surface residual to the already historical overall recent prior.
    global_form = residual(selected)
    surface_residual = residual(same)
    mix = len(same) / (len(same) + 8.0)
    form = mix * surface_residual + (1 - mix) * global_form
    aggregated = {}
    coverage = {}
    opportunities = {}
    for metric in ("serve", "return", "second_serve", "bp_save", "bp_convert"):
        numerator = denominator = n = 0
        for r in selected:
            pair = _counts(r)[metric]
            if pair is not None:
                numerator += pair[0]
                denominator += pair[1]
                n += 1
        aggregated[metric + "_rate"] = numerator / denominator if denominator else None
        coverage[metric] = n
        opportunities[metric] = denominator
    return {
        "canonical_player_id": player_id, "tour": tour.lower(),
        "matches_recent": len(selected), "matches_surface": len(same),
        "opponent_adjusted_form": global_form,
        "surface_opponent_adjusted_form": form,
        "stats": aggregated, "covered_matches": coverage,
        "stat_opportunities": opportunities,
    }


def reliability_gate(left: Mapping, right: Mapping,
                     model_probabilities: Mapping[str, Mapping]) -> dict:
    """Research-only abstention; independent models must score the SAME left player.

    Each entry is model_id -> {left_player_id: canonical ID, probability: float}.
    No confidence value is manufactured from complementary winner/loser sides.
    The score is NOT a calibrated win probability.
    """
    if left.get("tour") not in {"atp", "wta"} or left.get("tour") != right.get("tour"):
        raise ValueError("Both players must be on the same ATP/WTA tour")
    player = left.get("canonical_player_id")
    if not isinstance(player, str) or not player or not right.get("canonical_player_id") or player == right.get("canonical_player_id"):
        raise ValueError("Distinct reviewed canonical players required")
    invalid = {"eligible": False, "evidence_score": 0.0,
               "reasons": ["missing_or_invalid_model_disagreement"]}
    if not isinstance(model_probabilities, Mapping) or len(model_probabilities) < 2:
        return invalid
    ps = []
    for model_id, observation in model_probabilities.items():
        if (not isinstance(model_id, str) or not model_id.strip()
                or not isinstance(observation, Mapping)
                or observation.get("left_player_id") != player):
            return invalid
        p = observation.get("probability")
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
            return invalid
        ps.append(float(p))
    reasons = []
    n = min(int(left.get("matches_recent") or 0), int(right.get("matches_recent") or 0))
    surf = min(int(left.get("matches_surface") or 0), int(right.get("matches_surface") or 0))
    if n < 10: reasons.append("sparse_recent_history")
    if surf < 5: reasons.append("sparse_surface_history")
    rates = ("serve", "return", "second_serve", "bp_save", "bp_convert")
    cover = min(
        min(int(f.get("covered_matches", {}).get(k) or 0) for f in (left, right))
        for k in rates
    )
    if cover < 5: reasons.append("insufficient_verified_stat_coverage")
    # Merely having 5 boxscores is not 5 sufficiently sampled break-point
    # opportunities. Require actual observed denominators for both players.
    minimum_opportunities = {
        "serve": 300, "return": 300, "second_serve": 80,
        "bp_save": 15, "bp_convert": 15,
    }
    if any(min(int(f.get("stat_opportunities", {}).get(metric) or 0)
                   for f in (left, right)) < required
           for metric, required in minimum_opportunities.items()):
        reasons.append("insufficient_stat_opportunities")
    gap = max(ps) - min(ps)
    if n < 0 or surf < 0 or cover < 0 or surf > n or cover > n:
        raise ValueError("Contradictory evidence counts")
    if gap > 0.12: reasons.append("model_disagreement")
    # Transparent evidence index; not trained/calibrated on the holdout.
    score = round(0.25 * min(n / 20, 1.0) + 0.2 * min(surf / 10, 1.0)
                  + 0.35 * min(cover / 10, 1.0)
                  + 0.2 * max(0.0, 1.0 - gap / 0.20), 4)
    if score < 0.72: reasons.append("low_evidence_score")
    return {"eligible": not reasons, "evidence_score": score,
            "reasons": reasons, "recent_min": n, "surface_min": surf,
            "stat_coverage_min": cover, "model_probability_gap": round(gap, 4)}


DIL_FEATURE_NAMES = (
    "dil_serve_rate_diff", "dil_return_rate_diff", "dil_second_serve_rate_diff",
    "dil_bp_save_rate_diff", "dil_bp_convert_rate_diff",
    "dil_opponent_adjusted_form_diff", "dil_surface_opponent_form_diff",
    "dil_stats_known_both", "dil_min_recent_count", "dil_min_surface_count",
)


def pair_feature_projection(left: Mapping, right: Mapping) -> dict[str, float]:
    """Candidate-only numeric feature adapter, with explicit availability signal.

    Absent rates are neutral differences *only when paired with the known-both
    flag*. Never replace established model features or rewrite history.
    """
    if left.get("tour") not in {"atp", "wta"} or left.get("tour") != right.get("tour"):
        raise ValueError("Distinct ATP/WTA tour pairing required")
    a, b = left.get("canonical_player_id"), right.get("canonical_player_id")
    if not isinstance(a, str) or not a or not isinstance(b, str) or not b or a == b:
        raise ValueError("Both distinct reviewed CDB player IDs required")
    features = {}
    missing = 0
    for rate in ("serve", "return", "second_serve", "bp_save", "bp_convert"):
        l = left.get("stats", {}).get(rate + "_rate")
        r = right.get("stats", {}).get(rate + "_rate")
        if l is None or r is None:
            features["dil_" + rate + "_rate_diff"] = 0.0
            missing += 1
        else:
            if not all(isinstance(v, (float, int)) and math.isfinite(v)
                       and 0 <= v <= 1 for v in (l, r)):
                raise ValueError("Invalid source-derived rate")
            features["dil_" + rate + "_rate_diff"] = float(l) - float(r)
    for key, target in (
        ("opponent_adjusted_form", "dil_opponent_adjusted_form_diff"),
        ("surface_opponent_adjusted_form", "dil_surface_opponent_form_diff"),
    ):
        lv, rv = left.get(key), right.get(key)
        if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (lv, rv)):
            raise ValueError("Opponent-adjusted historical expectations unavailable")
        features[target] = float(lv) - float(rv)
    features["dil_stats_known_both"] = (5 - missing) / 5.0
    features["dil_min_recent_count"] = float(min(left["matches_recent"], right["matches_recent"]))
    features["dil_min_surface_count"] = float(min(left["matches_surface"], right["matches_surface"]))
    if set(features) != set(DIL_FEATURE_NAMES):
        raise AssertionError("Candidate DIL feature schema mismatch")
    return features
