"""Read-only TOP strategy replay on frozen full pre-match selection candidates.

Compare existing frozen TOP assignment with strict TOP >=80% and an ATP/WTA
main-tour-only research slice. Do not convert candidate assignments into issued
wagers. No paid providers, model changes, CDB writes or release mutations.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import re
from pathlib import Path

from replay_selection_reliability import (
    anchors, canonical_index, dt, eligible, load_snapshots, prepare,
)

CORE_TOP_PROBABILITY = 0.80
MIN_TOP_ODDS = 1.50
MIN_DEPTH = 0.80
MIN_SURFACE_EACH = 5
MAIN_LEVELS = frozenset(("ATP_MAIN", "WTA_MAIN"))


def prematch_category(row):
    """Use only immutable pre-start competition metadata, never canonical outcome."""
    level = str(row.get("competition") or "").strip().upper().replace("_", " ")
    name = str(row.get("tournament") or "").strip().upper()
    tour = str(row.get("tour") or "").strip().upper()
    value = level if level not in ("", "UNKNOWN", "NONE") else name
    if re.search(r"\bITF\b|\bM(?:15|25)\b|\bW(?:15|35|50|75|100)\b", value):
        return "ITF"
    if "CHALLENGER" in value:
        return "CHALLENGER"
    if re.search(r"\bWTA[ -]?125\b", value):
        return "WTA125"
    if "UTR" in value:
        return "UTR"
    if "GRAND SLAM" in level and tour in ("ATP", "WTA"):
        return tour + "_MAIN"
    if level.startswith("ATP") and tour == "ATP" and not re.search(r"\b125\b|CHALLENGER", level):
        return "ATP_MAIN"
    if level.startswith("WTA") and tour == "WTA" and not re.search(r"\b125\b", level):
        return "WTA_MAIN"
    # A generic 'tour=ATP/WTA' also covers many lower-tier fixtures.
    # Missing verified pre-match competition is not proof of main-tour status.
    return "UNKNOWN"


def strict_top(row):
    """Candidate selection; VALUE keeps its unchanged priority and exact <=15% gap."""
    return (
        row["quote_ok"]
        and row["public"] >= CORE_TOP_PROBABILITY
        and row["depth"] >= MIN_DEPTH
        and row["min_surface"] is not None
        and row["min_surface"] >= MIN_SURFACE_EACH
        and row["odds"] is not None
        and row["odds"] >= MIN_TOP_ODDS
        and not eligible(row, "value")
    )


def score(rows):
    """Hit rate and simple 1u hypothetical ROI from verified pre-start quotes."""
    finished = [r for r in rows if type(r.get("correct")) is bool]
    wins = sum(r["correct"] for r in finished)
    losses = len(finished) - wins
    units = sum((r["odds"] - 1.0) if r["correct"] else -1.0 for r in finished)
    return {
        "candidate_count": len(rows),
        "settled": len(finished), "wins": wins, "losses": losses,
        "pending_or_unmatched": len(rows) - len(finished),
        "hit_rate": wins / len(finished) if finished else None,
        "hypothetical_profit_1u": round(units, 6),
        "hypothetical_roi": units / len(finished) if finished else None,
    }


def evaluate(snapshots, canonical):
    index = canonical_index(canonical)
    counters = Counter()
    pool = defaultdict(list)
    seen = set()
    for day, snapshot in sorted(anchors(snapshots).items()):
        moment = dt(snapshot["generated_at"])
        for original in snapshot["rows"]:
            r = prepare(original, moment, day, index, counters)
            if r is None:
                continue
            identity = (r["model"], r["event"])
            if identity in seen:
                counters["repeat_candidate_skipped"] += 1
                continue
            seen.add(identity)
            r["competition_pre_match"] = prematch_category(original)
            pool[r["model"]].append(r)

    models = {}
    for model, records in sorted(pool.items()):
        original = [r for r in records if r["section"] == "top_daily" and r["quote_ok"]]
        strict = [r for r in records if strict_top(r)]
        main = [r for r in strict if r["competition_pre_match"] in MAIN_LEVELS]
        grouped = defaultdict(list)
        for r in strict:
            grouped[r["competition_pre_match"]].append(r)
        daily = defaultdict(lambda: defaultdict(list))
        for label, cohort in (("original_candidate_top", original),
                              ("strict_80_all_tours", strict),
                              ("strict_80_verified_atp_wta_only", main)):
            for r in cohort:
                daily[r["day"]][label].append(r)
        models[model] = {
            "scope": "frozen_selection_candidates_NOT_public_issuance",
            "original_candidate_top": score(original),
            "strict_80_all_tours": score(strict),
            "strict_80_verified_atp_wta_only": score(main),
            "strict_80_by_prematch_competition": {
                category: score(rows) for category, rows in sorted(grouped.items())
            },
            "per_day": {
                day: {label: score(cohorts.get(label, [])) for label in (
                    "original_candidate_top", "strict_80_all_tours",
                    "strict_80_verified_atp_wta_only")}
                for day, cohorts in sorted(daily.items())
            },
            "pre_match_competition_unknown": sum(
                r["competition_pre_match"] == "UNKNOWN" for r in records
            ),
            "all_pre_match_candidate_rows": len(records),
        }
    return {
        "schema": 1, "status": "RESEARCH_ONLY_NO_DEPLOY",
        "policy": {
            "strict_blinq_probability": CORE_TOP_PROBABILITY,
            "min_odds": MIN_TOP_ODDS,
            "min_data_depth": MIN_DEPTH,
            "min_surface_matches_each": MIN_SURFACE_EACH,
            "minimum_daily_top_count": 0,
            "value_priority": "UNCHANGED_ODDS_GE_1_80_SYMMETRIC_GAP_LE_15PCT",
            "aces_policy": "UNCHANGED",
            "prematch_competition_only": True,
        },
        "models": models,
        "diagnostics": dict(sorted(counters.items())),
        "safety": {
            "paid_provider_requests": 0, "cdb_writes": 0, "production_changes": 0,
            "warning": "Outcome-based comparison is retrospective and not a new blind holdout; missing outcomes are never graded.",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", nargs="+", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    import pandas as pd
    cols = [
        "match_id", "player1_id", "player2_id", "winner_id", "status",
        "scheduled_at", "tour", "tournament_level", "provider_context_json",
    ]
    matched = pd.read_parquet(args.canonical, columns=cols).to_dict("records")
    report = evaluate(load_snapshots(args.snapshots), matched)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "models": list(report["models"]),
                      "path": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
