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


def prematch_tier(row):
    """Retain exact ITF M/W event class only when frozen pre-match text proves it."""
    combined = " ".join((
        str(row.get("competition") or ""),
        str(row.get("tournament") or ""),
    )).upper()
    for match in ("M15", "M25", "W15", "W35", "W50", "W75", "W100"):
        if re.search(r"\b" + match + r"\b", combined):
            return "ITF_" + match
    return prematch_category(row)


def research_odds_band(odds):
    if odds is None:
        return "UNKNOWN"
    if odds < 1.70:
        return "1.50_to_1.69"
    if odds < 1.80:
        return "1.70_to_1.79"
    return "1.80_plus"


def predeclared_threshold_screen(records):
    """Outcome-blind fixed grid, chronological retrospective check, NOT deploy gate.

    This grid was specified only on 2026-11-07. Even its later historical
    window has been observed by selection policy research and is not a
    prospective blind experiment.
    """
    cutoff = "2026-11-01"
    prequalified = [
        r for r in records
        if r["quote_ok"] and r["odds"] is not None and r["odds"] >= MIN_TOP_ODDS
        and r["depth"] >= MIN_DEPTH
        and r["min_surface"] is not None and r["min_surface"] >= MIN_SURFACE_EACH
        and not eligible(r, "value")
    ]
    groups = {
        "ALL": prequalified,
        **{"tour:" + tour: [r for r in prequalified if r["tour"] == tour]
           for tour in sorted({r["tour"] for r in prequalified})},
        **{"tier:" + tier: [r for r in prequalified if r["competition_tier"] == tier]
           for tier in sorted({r["competition_tier"] for r in prequalified})},
        **{"odds:" + band: [r for r in prequalified if research_odds_band(r["odds"]) == band]
           for band in sorted({research_odds_band(r["odds"]) for r in prequalified})},
    }
    result = {}
    for group, rows in sorted(groups.items()):
        options = {}
        for threshold in (0.65, 0.70, 0.75, 0.80, 0.85):
            qualified = [r for r in rows if r["public"] >= threshold]
            history = [r for r in qualified if r["day"] < cutoff]
            later = [r for r in qualified if r["day"] >= cutoff]
            earlier_m = score(history)
            later_m = score(later)
            sufficient = (earlier_m["settled"] >= 30 and later_m["settled"] >= 30
                          and earlier_m["pending_or_unmatched"] <= .1 * max(1,len(history))
                          and later_m["pending_or_unmatched"] <= .1 * max(1,len(later)))
            options[str(threshold)] = {
                "development_before_2026_11_01": earlier_m,
                "chronological_review_from_2026_11_01": later_m,
                "min_sample_gate": "DESCRIPTIVE_ONLY" if sufficient else "INSUFFICIENT_COHORT",
            }
        result[group] = options
    return {
        "status":"RETROSPECTIVE_EXPLORATORY_NOT_BLIND",
        "fixed_cutoff":"2026-11-01",
        "all_sections":result,
        "warning":"Do not select a winning threshold based on the later outcomes; this is not a clean prospective holdout.",
    }


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
            r["competition_tier"] = prematch_tier(original)
            pool[r["model"]].append(r)

    def funnel(rows):
        counts = Counter()
        for record in rows:
            counts["candidate_rows"] += 1
            if not record["quote_ok"]:
                counts["missing_verified_prestart_quote"] += 1
                continue
            counts["quote_valid"] += 1
            if record["odds"] < MIN_TOP_ODDS:
                counts["quote_below_min_1_50"] += 1
                continue
            counts["odds_ge_1_50"] += 1
            if record["depth"] < MIN_DEPTH or record["min_surface"] is None or record["min_surface"] < MIN_SURFACE_EACH:
                counts["quality_gate_rejected"] += 1
                continue
            counts["quality_pass"] += 1
            if record["public"] < CORE_TOP_PROBABILITY:
                counts["below_fixed_80_probability"] += 1
                continue
            counts["probability_ge_80"] += 1
            if eligible(record, "value"):
                counts["VALUE_claims_precedence"] += 1
                continue
            counts["strict_TOP_pass"] += 1
        return dict(sorted(counts.items()))

    models = {}
    for model, records in sorted(pool.items()):
        original = [r for r in records if r["section"] == "top_daily" and r["quote_ok"]]
        strict = [r for r in records if strict_top(r)]
        main = [r for r in strict if r["competition_pre_match"] in MAIN_LEVELS]
        old_ids = {r["event"] for r in original}
        new_ids = {r["event"] for r in strict}
        # The arms have different denominators. Explain exact same-day overlap
        # rather than presenting their overall accuracy difference as causal.
        overlap = [r for r in strict if r["event"] in old_ids]
        omitted = [r for r in original if r["event"] not in new_ids]
        added = [r for r in strict if r["event"] not in old_ids]
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
            "exact_same_offer_reconciliation": {
                "both": score(overlap),
                "original_only": score(omitted),
                "strict_only": score(added),
                "same_day_and_model": True,
                "interpretation": "Descriptive same-slate membership, never paired equal-capacity uplift",
            },
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
            "exploratory_fixed_grid": predeclared_threshold_screen(records),
            "eligibility_funnel": funnel(records),
            "eligibility_funnel_by_tour": {
                tour: funnel([r for r in records if r["tour"] == tour])
                for tour in sorted({r["tour"] for r in records})
            },
            "eligibility_funnel_by_pre_match_competition": {
                category: funnel([r for r in records if r["competition_pre_match"] == category])
                for category in sorted({r["competition_pre_match"] for r in records})
            },
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
