"""Private, common-cutoff champion/challenger/market comparison."""

from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
import random
import re

from settle_frozen_721_shadow import completed_matches_for_pending
from tbt.models.metrics import evaluate_probabilities
from tbt.services.market_anchored_rank import _num, _ts
from tbt.services.market_rank_shadow import MIN_LEAD_SECONDS, SECTIONS, _quote_fair
from tbt.services.market_selection import _belongs_to_public_offer_day
from tbt.services.shadow_evaluation import update_shadow_ledger


FIELD = "paired_market_shadow"
SCHEMA = 1
MIN_REVIEW_PAIRS = 400
TOP_THRESHOLDS = (0.50, 0.55, 0.60)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                             separators=(",", ":")).encode()).hexdigest()


def _pair_key(capture):
    return tuple(capture[key] for key in (
        "champion_version", "champion_sha256", "candidate_version", "candidate_sha256"
    ))


def verified_captures(history):
    for snapshot in history["snapshots"]:
        capture = snapshot.get(FIELD)
        if capture is not None:
            data = {k: v for k, v in capture.items() if k != "sha256"}
            if data.get("schema") != SCHEMA or _digest(data) != capture.get("sha256"):
                raise ValueError("Invalid paired market receipt digest")
            yield capture


def _identity(row):
    return (
        str(row.get("id") or ""), str(row.get("event_id") or ""),
        str(row.get("tour") or "").upper(), _ts(row.get("scheduled_at")),
        str((row.get("player1") or {}).get("id") or ""),
        str((row.get("player2") or {}).get("id") or ""),
    )


def _quote(row, clock):
    if _quote_fair(row, clock) is None:
        return None
    market = row["match_winner_market"]
    betting = row["betting"]
    source_clock = _ts(market.get("captured_at"))
    if source_clock is None or source_clock > clock or _ts(betting.get("captured_at")) != source_clock:
        return None
    o1, o2 = (_num(market.get(f"player{i}_odds")) for i in (1, 2))
    if o1 is None or o2 is None or min(o1, o2) <= 1:
        return None
    selected_odds = o1 if str(betting["selection_id"]) == str(row["player1"]["id"]) else o2
    recorded_odds = _num(betting.get("odds"))
    if recorded_odds is None or not math.isclose(selected_odds, recorded_odds, abs_tol=0.0001):
        return None
    inv1, inv2 = 1 / o1, 1 / o2
    fair = inv1 / (inv1 + inv2)
    if not math.isclose(fair, float(market["player1_implied_probability"]), abs_tol=0.0001):
        return None
    return {
        "market_p1": fair, "player1_odds": o1, "player2_odds": o2,
        "provider_id": str(market["provider_id"]), "source": market["source"],
        "bookmaker": str(market.get("bookmaker") or market.get("source_id") or ""),
        "provider_event_id": str(market.get("provider_event_id") or row["event_id"]),
        "source_captured_at": source_clock.isoformat(),
    }


def build_capture(history, champion, candidate, sections, *, observed_at,
                  public_offer_day, champion_sha256, candidate_sha256):
    """Freeze the first priced exact pair for an event within the model cohort."""
    clock = _ts(observed_at)
    if clock is None or not all(
        re.fullmatch(r"[0-9a-f]{64}", value or "")
        for value in (champion_sha256, candidate_sha256)
    ):
        raise ValueError("Paired market evidence requires a real clock and both artifact hashes")
    if not candidate:
        return None, {"missing_active_candidate": 1}

    versions = {str(row.get("model_version") or "") for row in candidate}
    champion_versions = {str(row.get("model_version") or "") for row in champion}
    if (len(versions) != 1 or len(champion_versions) != 1 or "" in versions
            or "" in champion_versions or versions == champion_versions):
        raise ValueError("Paired market evidence requires one distinct model pair")
    capture = {
        "schema": SCHEMA, "public_offer_day": public_offer_day,
        "captured_at": clock.isoformat(),
        "champion_version": champion_versions.pop(), "champion_sha256": champion_sha256,
        "candidate_version": versions.pop(), "candidate_sha256": candidate_sha256,
        "research_only": True,
    }
    prior_events = {
        row["event_id"] for old in verified_captures(history)
        if _pair_key(old) == _pair_key(capture) for row in old["rows"]
    }
    by_candidate = defaultdict(list)
    for row in candidate:
        by_candidate[_identity(row)].append(row)
    by_section = defaultdict(list)
    for section, field in SECTIONS.items():
        for card in sections.get(field, ()):
            by_section[_identity(card)].append(
                (section, str((card.get("betting") or {}).get("selection_id") or ""))
            )

    event_counts = Counter(str(row.get("event_id") or "") for row in champion)
    counts = Counter()
    rows = []
    for row in champion:
        identity = _identity(row)
        mid, event, tour, start, p1, p2 = identity
        if not _belongs_to_public_offer_day(row, public_offer_day):
            continue
        counts["offer_day_fixtures"] += 1
        if (not all(identity) or p1 == p2 or event_counts[event] != 1
                or len(by_candidate[identity]) != 1):
            counts["missing_or_ambiguous_pair"] += 1
            continue
        alternative = by_candidate[identity][0]
        a_created, b_created = _ts(row.get("created_at")), _ts(alternative.get("created_at"))
        if (start - clock).total_seconds() <= MIN_LEAD_SECONDS or not (
            a_created is not None and a_created == b_created and a_created <= clock
        ):
            counts["invalid_pair_clock"] += 1
            continue
        if event in prior_events:
            counts["already_captured"] += 1
            continue
        quote = _quote(row, clock)
        if quote is None:
            counts["no_verified_two_way_quote"] += 1
            continue
        values = [_num(data["player1"].get("probability")) for data in (row, alternative)]
        adjusted = _num(row.get("blinq_probability"))
        winner = str(row.get("winner_id") or "")
        if (any(p is None or not 0 < p < 1 for p in values)
                or adjusted is None or not .5 <= adjusted < 1 or winner not in (p1, p2)):
            counts["invalid_probability"] += 1
            continue
        prod, chal = values
        sections_for_row = {
            section: side for section, side in by_section[identity] if side in (p1, p2)
        }
        rows.append({
            "match_id": mid, "event_id": event, "tour": tour, "surface": row.get("surface"),
            "player1_id": p1, "player2_id": p2, "scheduled_at": start.isoformat(),
            "model_created_at": a_created.isoformat(),
            "production_player1_probability": prod, "challenger_player1_probability": chal,
            "adjusted_p1": adjusted if winner == p1 else 1 - adjusted,
            "data_depth": _num(row.get("data_depth")), "sections": sections_for_row, **quote,
        })
    counts["new_priced_pairs"] = len(rows)
    if not rows:
        return None, dict(counts)
    capture["counts"] = dict(counts)
    capture["rows"] = sorted(rows, key=lambda row: row["event_id"])
    capture["sha256"] = _digest(capture)
    return capture, dict(counts)


def _blend(market, model):
    def logit(p):
        return math.log(p / (1 - p))

    z = .8 * logit(market) + .2 * logit(model)
    return 1 / (1 + math.exp(-z))


def _score(rows, *, section=None):
    metrics = {}
    sides = [section is None or r["sections"][section] == r["player1_id"] for r in rows]
    truth = [r["target_player1_win"] if side else 1 - r["target_player1_win"]
             for r, side in zip(rows, sides)]
    for field in ("production_player1_probability", "challenger_player1_probability",
                  "adjusted_p1", "market_p1", "market_80_champion_20", "market_80_candidate_20"):
        probs = [r[field] if side else 1 - r[field] for r, side in zip(rows, sides)]
        scores = evaluate_probabilities(truth, probs)
        metrics[field] = {k: v for k, v in scores.items()
                          if k in ("accuracy", "brier_score", "log_loss", "ece_10")}
        if rows:
            metrics[field]["mean_probability"] = sum(probs) / len(rows)
    return {
        "n": len(rows), "metrics": metrics,
        "target_rate": sum(truth) / len(rows) if rows else None,
        "candidate_minus_market_log_loss": _day_interval(rows, "challenger_player1_probability"),
        "blend_minus_market_log_loss": _day_interval(rows, "market_80_champion_20"),
    }


def _day_interval(rows, field):
    days = defaultdict(list)
    for r in rows:
        value, market = r[field], r["market_p1"]
        if not r["target_player1_win"]:
            value, market = 1 - value, 1 - market
        delta = math.log(max(1e-6, min(1 - 1e-6, market))) - math.log(
            max(1e-6, min(1 - 1e-6, value))
        )
        days[r["scheduled_at"][:10]].append(delta)
    if not days:
        return None
    aggregates = [(sum(values), len(values)) for _, values in sorted(days.items())]
    result = {"days": len(days), "delta": sum(s for s, _ in aggregates) / len(rows), "ci95": None}
    if len(days) >= 3:
        rng = random.Random(27)
        samples = []
        for _ in range(1000):
            sample = rng.choices(aggregates, k=len(aggregates))
            samples.append(sum(s for s, _ in sample) / sum(n for _, n in sample))
        samples.sort()
        result["ci95"] = [samples[25], samples[974]]
    return result


def _top_veto(rows, threshold):
    selected = [r for r in rows if "top" in r["sections"]]
    kept = []
    for r in selected:
        side_one = r["sections"]["top"] == r["player1_id"]
        fair = r["market_p1"] if side_one else 1 - r["market_p1"]
        if fair + 1e-12 >= threshold:
            kept.append((r, side_one))
    returns = [
        (r["player1_odds"] if side_one else r["player2_odds"])
        if bool(r["target_player1_win"]) == side_one else 0
        for r, side_one in kept if r["status"] == "settled"
    ]
    return {
        "baseline_priced_top": len(selected), "kept": len(kept), "settled": len(returns),
        "wins": sum(value > 0 for value in returns),
        "flat_stake_roi": sum(returns) / len(returns) - 1 if returns else None,
    }


def compare(histories, matches, *, asof):
    """Evaluate immutable captures against the existing verified canonical join."""
    clock = _ts(asof)
    if clock is None:
        raise ValueError("Paired market evaluation requires an aware clock")
    cohorts = defaultdict(dict)
    captures = sorted((c for h in histories for c in verified_captures(h)),
                      key=lambda c: _ts(c["captured_at"]))
    for capture in captures:
        if _ts(capture["captured_at"]) > clock:
            continue
        key = _pair_key(capture)
        for row in capture["rows"]:
            rows = cohorts[key]
            old = rows.get(row["event_id"])
            if old is not None:
                if any(old[k] != row[k] for k in ("tour", "player1_id", "player2_id")):
                    raise ValueError("Conflicting persisted paired market event identity")
                continue
            rows[row["event_id"]] = dict(
                row, captured_at=capture["captured_at"], status="pending",
                market_80_champion_20=_blend(row["market_p1"], row["production_player1_probability"]),
                market_80_candidate_20=_blend(row["market_p1"], row["challenger_player1_probability"]),
            )
    reports = []
    for key, events in cohorts.items():
        rows = list(events.values())
        match_ids = [row["match_id"] for row in rows]
        if len(match_ids) != len(set(match_ids)):
            raise ValueError("Conflicting persisted paired market match identity")
        accepted, _ = completed_matches_for_pending(rows, matches, clock)
        outcomes = update_shadow_ledger(rows, completed_matches=accepted, now=clock)
        settled = [r for r in outcomes if r["status"] == "settled"]
        by_tour = {tour: _score([r for r in settled if r["tour"] == tour])
                   for tour in ("ATP", "WTA")}
        reports.append({
            "champion_version": key[0], "champion_sha256": key[1],
            "candidate_version": key[2], "candidate_sha256": key[3],
            "outcomes": dict(Counter(r["status"] for r in outcomes)),
            "settled_days": len({r["scheduled_at"][:10] for r in settled}),
            "all": _score(settled), "by_tour": by_tour,
            "issued_policy_cohorts": {
                section: _score([r for r in settled if section in r["sections"]], section=section)
                for section in SECTIONS
            },
            "depth_below_050": _score([r for r in settled if r["data_depth"] is not None
                                       and r["data_depth"] < .5]),
            "top_veto_no_refill": {str(t): _top_veto(outcomes, t) for t in (0.0, *TOP_THRESHOLDS)},
            "minimum_400_met": len(settled) >= MIN_REVIEW_PAIRS,
        })
    return {"research_only": True, "automatic_promotion": False, "cohorts": reports}
