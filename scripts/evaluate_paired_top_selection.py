"""Private sport-first, verified-price-second paired TOP replay.

Never accepts a price as a sports feature. This is historical research,
NOT an exact reconstruction of issued TOP or an unseen evaluation period.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import json
import math
import random
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bratislava")


def stamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError("Invalid timestamp") from None
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Naive timestamp is forbidden")
    return dt.astimezone(timezone.utc)


def valid_number(value, *, minimum=0, maximum=1):
    try:
        f = float(value)
    except (ValueError, TypeError):
        raise ValueError("Invalid numeric value") from None
    if not math.isfinite(f) or not minimum <= f <= maximum:
        raise ValueError("Out-of-range number")
    return f


def auc(y, scores):
    """Tie-aware AUC; None if only one class is present."""
    if len(y) != len(scores):
        raise ValueError("AUC label/score mismatch")
    pos = sum(int(bool(t)) for t in y)
    neg = len(y) - pos
    if not pos or not neg:
        return None
    sorted_pairs = sorted(zip(scores, y))
    rank_sum, index = 0., 0
    while index < len(sorted_pairs):
        end = index + 1
        while end < len(sorted_pairs) and sorted_pairs[end][0] == sorted_pairs[index][0]:
            end += 1
        avg_rank = (index + 1 + end) / 2.
        rank_sum += avg_rank * sum(int(bool(t)) for _, t in sorted_pairs[index:end])
        index = end
    return (rank_sum - pos*(pos+1)/2.)/(pos*neg)


def statistics(rows, model):
    n = len(rows)
    if not n:
        return {"n": 0, "wins": 0, "accuracy": None,
                "mean_confidence": None, "confidence_accuracy_auc": None}
    predictions = [r["predictions"][model] for r in rows]
    wins = [p["correct"] for p in predictions]
    confidences = [p["confidence"] for p in predictions]
    y = [p["target_player1_win"] for p in predictions]
    p1 = [p["player1_probability"] for p in predictions]
    return {
        "n": n, "wins": sum(wins),
        "accuracy": sum(wins)/n,
        "mean_confidence": sum(confidences)/n,
        "calibration_gap": sum(wins)/n - sum(confidences)/n,
        "winner_roc_auc": auc(y, p1),
        "confidence_accuracy_auc": auc(wins, confidences),
        "brier_selected_side": sum((p["confidence"] - p["correct"])**2 for p in predictions)/n,
    }


def paired_day_bootstrap(production, candidate, repetitions=1000):
    """Paired candidate-minus-champion accuracy, resampling local betting days.

    Only fixtures qualified by BOTH sports+price selection arms are compared.
    A selection-volume difference is reported separately rather than silently
    counting missing/unpriced fixtures as losses.
    """
    left = {r["match_id"]: r for r in production}
    right = {r["match_id"]: r for r in candidate}
    common = sorted(set(left) & set(right))
    by_day = defaultdict(list)
    for key in common:
        a, b = left[key], right[key]
        if a["day"] != b["day"]:
            raise ValueError("Paired betting-day mismatch")
        by_day[a["day"]].append(
            b["predictions"]["candidate"]["correct"] -
            a["predictions"]["production"]["correct"])
    days = sorted(by_day)
    deltas = [d for day in days for d in by_day[day]]
    observed = sum(deltas)/len(deltas) if deltas else None
    if len(days) < 3:
        return {"common_n": len(common), "days": len(days),
                "delta_accuracy": observed, "day_bootstrap_ci95": None}
    rng = random.Random(721)
    distribution = []
    for _ in range(repetitions):
        chosen = [rng.choice(days) for _ in days]
        differences = [d for day in chosen for d in by_day[day]]
        distribution.append(sum(differences)/len(differences))
    distribution.sort()
    return {"common_n": len(common), "days": len(days),
            "delta_accuracy": observed,
            "day_bootstrap_ci95": [
                distribution[int(.025*(repetitions-1))],
                distribution[int(.975*(repetitions-1))],
            ]}


def evaluate(holdout, quotes, *, confidence_floor=.60, min_depth=.8,
             min_surface_matches=5):
    if (holdout.get("schema") != 1 or
            holdout.get("historical_prices_included") is not False or
            holdout.get("evaluation") != "previously_inspected_chronological_holdout_not_prospective"):
        raise ValueError("Untrusted paired PIT score source")
    scores = holdout.get("rows")
    if not isinstance(scores, list) or not scores:
        raise ValueError("Missing paired scores")
    if not isinstance(quotes, list):
        raise ValueError("Historical quote list required")
    quote_by_id = {}
    for quote in quotes:
        key = quote["match_id"]
        if key in quote_by_id:
            raise ValueError("Duplicate or ambiguous market quote identity")
        quote_by_id[key] = quote
    seen = set()
    all_days = set()
    considered = defaultdict(list)
    totals = {"paired_rows": len(scores), "price_missing": 0,
              "price_after_start": 0, "sports_ineligible": 0,
              "market_qualified_per_model": {"production": 0, "candidate": 0},
              "below_sports_confidence_per_model": {"production": 0, "candidate": 0},
              "below_price_floor_per_model": {"production": 0, "candidate": 0}}
    for row in scores:
        key = row["match_id"]
        if key in seen:
            raise ValueError("Duplicate scored fixture")
        seen.add(key)
        start = stamp(row["scheduled_at"])
        all_days.add((start.astimezone(TZ) - timedelta(hours=6)).date().isoformat())
        if row["player1_id"] == row["player2_id"] or row["winner_id"] not in {
                row["player1_id"], row["player2_id"]}:
            raise ValueError("Invalid player/winner identity")
        y = int(row["target_player1_win"])
        if y not in (0, 1) or (row["winner_id"] == row["player1_id"]) != bool(y):
            raise ValueError("Winner side/label collision")
        ev = row["pre_match_feature_evidence"]
        depth = valid_number(ev["data_depth"])
        sample = valid_number(ev["surface_history_count"], maximum=1000000)
        # Coherent sports gate, independent of bookmaker prices.
        if depth < min_depth or sample < min_surface_matches:
            totals["sports_ineligible"] += 1
            continue
        quote = quote_by_id.get(key)
        if quote is None:
            totals["price_missing"] += 1
            continue
        if (quote.get("player1_id") != row["player1_id"] or
                quote.get("player2_id") != row["player2_id"]):
            raise ValueError("Quote player orientation mismatch")
        captured = stamp(quote["captured_at"])
        if captured >= start:
            totals["price_after_start"] += 1
            continue
        odds = [valid_number(quote["odds_player1"], minimum=1.000001, maximum=10000),
                valid_number(quote["odds_player2"], minimum=1.000001, maximum=10000)]
        day = (start.astimezone(TZ) - timedelta(hours=6)).date().isoformat()
        predictions = {}
        for model in ("production", "candidate"):
            p = valid_number(row[f"{model}_player1_probability"])
            if not 0 < p < 1:
                raise ValueError("Degenerate probability")
            selected = int(p < .5)
            confidence = max(p, 1-p)
            if confidence + 1e-12 < confidence_floor:
                totals["below_sports_confidence_per_model"][model] += 1
                continue
            if odds[selected] < 1.5:
                totals["below_price_floor_per_model"][model] += 1
                continue
            totals["market_qualified_per_model"][model] += 1
            predictions[model] = {
                "confidence": confidence,
                "player1_probability": p,
                "target_player1_win": y,
                "correct": int((p >= .5) == bool(y)),
                "odds": odds[selected],
            }
        for model, prediction in predictions.items():
            considered[model].append({
                "match_id": key, "day": day,
                "tour": row["tour"], "competition": row["competition"],
                "predictions": {model: prediction},
            })
    result = {}
    for model in ("production", "candidate"):
        rows = considered[model]
        by_day = defaultdict(list)
        for row in rows:
            by_day[row["day"]].append(row)
        for items in by_day.values():
            items.sort(key=lambda r: (-r["predictions"][model]["confidence"], r["match_id"]))
        daily = {day: len(by_day.get(day, [])) for day in sorted(all_days)}
        result[model] = {
            "qualified": len(rows),
            "days_with_3plus": sum(n>=3 for n in daily.values()),
            "days_evaluated": len(all_days),
            "days": daily,
            "all_qualified": statistics(rows, model),
            "top_3": statistics([r for items in by_day.values() for r in items[:3]], model),
            "top_5": statistics([r for items in by_day.values() for r in items[:5]], model),
            "top_7": statistics([r for items in by_day.values() for r in items[:7]], model),
            "by_level": {
                level: statistics([r for r in rows if (
                    "challenger" in r["competition"].lower() if level == "challenger" else
                    "itf" in r["competition"].lower() if level == "itf" else
                    ("wta" in r["competition"].lower() or "atp" in r["competition"].lower())
                    and "challenger" not in r["competition"].lower() and
                    "itf" not in r["competition"].lower()
                )], model) for level in ("main_tour", "challenger", "itf")},
            "by_tour": {tour: statistics([r for r in rows if r["tour"].lower() == tour], model)
                        for tour in ("atp", "wta")},
        }
    return {
        "schema": 1, "status": "RESEARCH_REPLAY_NOT_NATIVE_ISSUED_TOP",
        "same_fixture_source": holdout["holdout_fingerprint"],
        "model_versions": {x: holdout[x+"_version"] for x in ("candidate", "champion")},
        "conditions": {"sports_confidence_floor": confidence_floor,
                       "sports_depth": min_depth, "min_surface_matches": min_surface_matches,
                       "subsequent_verified_odds": 1.5, "forced_fill": False},
        "limitations": ["Inspected offline holdout is not new/untouched.",
                        "Historical quote availability is not the same as morning publication.",
                        "Native TOP rejection rules and actual issued snapshot require separate replay.",
                        "No sports model was fitted or tuned by this script."],
        "counts": totals, "comparison": result,
        "paired_common_qualifiers": paired_day_bootstrap(
            considered["production"], considered["candidate"]),
    }



def compare_confidence_floors(holdout, quotes, *, lower=.60, higher=.65):
    """Compare predeclared 60% vs 65% sports gates on the SAME priced rows.

    Historical odds >=1.50 remain a separate, later eligibility check.
    Neither the odds nor any model correctness is used to rank candidates.
    Additional outcomes are observed research diagnostics, not a sports
    model fitting objective and not an approval to lower the live TOP gate.
    """
    if not (.5 <= lower < higher < 1.):
        raise ValueError("Expected two ordered sports confidence floors")
    primary = evaluate(holdout, quotes, confidence_floor=lower)
    reference = evaluate(holdout, quotes, confidence_floor=higher)
    increments = {}
    for model in ("production", "candidate"):
        lo = primary["comparison"][model]
        hi = reference["comparison"][model]
        extra = lo["all_qualified"]["n"] - hi["all_qualified"]["n"]
        wins = lo["all_qualified"]["wins"] - hi["all_qualified"]["wins"]
        top3_extra = lo["top_3"]["n"] - hi["top_3"]["n"]
        top3_wins = lo["top_3"]["wins"] - hi["top_3"]["wins"]
        if not (0 <= wins <= extra and 0 <= top3_wins <= top3_extra):
            raise ValueError("Lower sports threshold did not yield monotonic picks")
        increments[model] = {
            "new_price_qualified_picks": extra,
            "correct_among_new": wins,
            "accuracy_among_new": wins / extra if extra else None,
            "new_top3_daily_slots": top3_extra,
            "correct_among_new_top3_slots": top3_wins,
            "days_with_3plus_delta": lo["days_with_3plus"] - hi["days_with_3plus"],
            "days_with_3plus_at_60": lo["days_with_3plus"],
            "days_with_3plus_at_65": hi["days_with_3plus"],
        }
    return {
        "primary": primary, "reference_65": reference,
        "increment_from_65_to_60": {
            "lower_sports_floor": lower, "reference_sports_floor": higher,
            "verified_minimum_odds_unchanged": 1.5,
            "predeclared_evidence_not_betting_ev": True,
            "by_model": increments,
        },
    }


def read_json(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fp:
        return json.load(fp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paired", required=True)
    parser.add_argument("--quotes", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = evaluate(read_json(args.paired), read_json(args.quotes))
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"status": result["status"], "counts": result["counts"]}))


if __name__ == "__main__":
    main()
