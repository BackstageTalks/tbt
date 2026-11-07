"""Audit ONLY originally issued winner bets against independent canonical results.

Reads immutable production market-publication ledger and canonical CDB (read-only).
Never treats a selector candidate as publicly issued, never treats missing outcome
as a loss, never infers a pre-start quote from post-match odds, never changes CDB.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import timedelta
import hashlib
import json
import math
from pathlib import Path
import re

from replay_selection_reliability import (
    FINISHED, _canonical_schedule_consistent, _void_or_unsettled,
    canonical_index, dt, verify_pins,
)

PUBLIC_SECTIONS = {"top_daily", "value"}
MIN_PRESTART = timedelta(minutes=15)


def category(row):
    """Conservative frozen issuance-time tournament-level classification."""
    level = str(row.get("competition") or "").strip().upper().replace("_", " ")
    tournament = str(row.get("tournament") or "").strip().upper()
    tour = str(row.get("tour") or "").strip().upper()
    combined = level + " " + tournament
    for regex, label in (
        (r"\bM15\b", "ITF_M15"), (r"\bM25\b", "ITF_M25"),
        (r"\bW15\b", "ITF_W15"), (r"\bW35\b", "ITF_W35"),
        (r"\bW50\b", "ITF_W50"), (r"\bW75\b", "ITF_W75"),
        (r"\bW100\b", "ITF_W100"),
    ):
        if re.search(regex, combined):
            return label
    if re.search(r"\bITF\b", combined):
        return "ITF_LEVEL_UNKNOWN"
    if "CHALLENGER" in combined:
        return "CHALLENGER"
    if re.search(r"\bWTA[\s-]*125\b", combined):
        return "WTA125"
    if "UTR" in combined:
        return "UTR"
    # Only an explicitly frozen pre-match level is enough to classify main tour.
    if tour == "ATP" and (re.search(r"\bATP[\s-]*(?:250|500|1000)\b", level)
                          or "MASTERS" in level or "GRAND SLAM" in level):
        return "ATP_MAIN"
    if tour == "WTA" and (re.search(r"\bWTA[\s-]*(?:250|500|1000)\b", level)
                          or "GRAND SLAM" in level):
        return "WTA_MAIN"
    return "UNKNOWN"


def value_band(v, boundaries):
    if not isinstance(v, (float, int)) or not math.isfinite(v):
        return "UNKNOWN"
    for bound in boundaries:
        if v < bound:
            return "<" + str(bound)
    return ">=" + str(boundaries[-1])


def finite_positive(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def grade_issued(ledger, canon):
    """Independent exact-identity readback and conservative issuance dedupe."""
    index = canonical_index(canon)
    rejected = Counter()
    unique = {}
    raw_pubs = 0
    for row in ledger:
        if not isinstance(row, dict):
            rejected["invalid_ledger_row"] += 1
            continue
        if row.get("excluded_reason") or row.get("settlement_quarantine"):
            rejected["quarantined_ledger_row"] += 1
            continue
        event = str(row.get("event_id") or row.get("id") or "").strip()
        p1 = str((row.get("player1") or {}).get("id") or "")
        p2 = str((row.get("player2") or {}).get("id") or "")
        scheduled = row.get("scheduled_at")
        for p in row.get("market_publications") or []:
            if not isinstance(p, dict) or p.get("market") != "match_winner":
                continue
            if str(p.get("section") or "") not in PUBLIC_SECTIONS:
                continue
            if not p.get("issued_at"):
                rejected["not_issued"] += 1
                continue
            raw_pubs += 1
            if p.get("excluded_reason") or p.get("publication_status") not in ("published", None, ""):
                rejected["excluded_or_unpublished"] += 1
                continue
            selection = str(p.get("selection_id") or "")
            key = (event, "match_winner", selection)
            if not event or not p1 or not p2 or p1 == p2 or selection not in {p1, p2}:
                rejected["ambiguous_issued_identity"] += 1
                continue
            if str(row.get("winner_id") or "") != selection:
                rejected["selection_mismatch_to_prediction"] += 1
                continue
            quote = finite_positive(p.get("odds"))
            if quote is None or quote <= 1.0:
                rejected["missing_or_invalid_issued_price"] += 1
                continue
            try:
                issued = dt(p["issued_at"])
                planned = dt(scheduled)
            except ValueError:
                rejected["invalid_publication_time"] += 1
                continue
            if issued >= planned - MIN_PRESTART:
                rejected["issued_inside_15_min_cutoff"] += 1
                continue
            stored_result = p.get("result") if isinstance(p.get("result"), dict) else {}
            if stored_result.get("status") == "void" or stored_result.get("correct") not in (True, False):
                rejected["void_or_unsettled_issued"] += 1
                continue
            matched = index.get(event)
            if matched is None:
                rejected["missing_canonical_event"] += 1
                continue
            ids = {str(matched.get("player1_id") or ""), str(matched.get("player2_id") or "")}
            if ids != {p1, p2}:
                rejected["canonical_player_conflict"] += 1
                continue
            if str(matched.get("tour") or "").lower() not in ("", str(row.get("tour") or "").lower()):
                rejected["canonical_tour_conflict"] += 1
                continue
            if not _canonical_schedule_consistent(matched.get("scheduled_at"), planned):
                rejected["canonical_schedule_conflict"] += 1
                continue
            if _void_or_unsettled(matched, ids):
                rejected["canonical_unsettled_or_void"] += 1
                continue
            canonical_winner = str(matched.get("winner_id") or "")
            verified_correct = selection == canonical_winner
            if stored_result.get("correct") is not verified_correct:
                rejected["settlement_conflict"] += 1
                continue
            try:
                actual_start = dt(matched.get("scheduled_at"))
            except ValueError:
                rejected["invalid_canonical_schedule"] += 1
                continue
            if issued >= actual_start - MIN_PRESTART:
                rejected["late_vs_actual_start"] += 1
                continue
            frozen_capture = p.get("captured_at")
            pit_quote = False
            if frozen_capture:
                try:
                    captured = dt(frozen_capture)
                    pit_quote = captured <= issued and captured < actual_start - MIN_PRESTART
                except ValueError:
                    pass
            if not pit_quote:
                rejected["no_verified_price_timestamp"] += 1

            evidence = p.get("issued_snapshot") or p.get("prepared_snapshot") or {}
            if not isinstance(evidence, dict):
                evidence = {}
            probability = finite_positive(evidence.get("blinq_probability"))
            if probability is None:
                probability = finite_positive(p.get("blinq_probability"))
            if probability is not None and probability > 1.0:
                probability = None
            depth = finite_positive(evidence.get("data_depth"))
            if depth is None:
                depth = finite_positive(row.get("data_depth"))
            entry = {
                "event_id": event, "section": p["section"], "issued": issued,
                "category": category(row), "correct": verified_correct,
                "odds": quote, "profit": quote - 1 if verified_correct else -1.0,
                "pit_quote": pit_quote, "probability": probability, "depth": depth,
                "model": str(evidence.get("model_version") or p.get("model_version") or row.get("model_version") or "UNKNOWN"),
            }
            previous = unique.get(key)
            if previous is None:
                unique[key] = entry
            else:
                rejected["semantic_duplicate"] += 1
                if (entry["correct"] != previous["correct"]
                        or abs(entry["odds"] - previous["odds"]) > 1e-7):
                    rejected["duplicate_conflict"] += 1
                    unique[key] = None
                elif entry["issued"] < previous["issued"]:
                    unique[key] = entry
    return [x for x in unique.values() if x], dict(sorted(rejected.items())), raw_pubs


def aggregate(rows):
    wins = sum(x["correct"] for x in rows)
    n = len(rows)
    profit = sum(x["profit"] for x in rows)
    return {
        "n": n, "wins": wins, "losses": n - wins,
        "hit_rate": round(wins / n, 8) if n else None,
        "profit_1u": round(profit, 6),
        "roi_1u": round(profit / n, 8) if n else None,
    }


def audit(ledger, canonical):
    entries, rejected, raw_pubs = grade_issued(ledger, canonical)
    def groups(seq, fn):
        d = defaultdict(list)
        for x in seq:
            d[fn(x)].append(x)
        return {key: aggregate(rows) for key, rows in sorted(d.items())}
    by_date = groups(entries, lambda x: x["issued"].date().isoformat())
    verified = [r for r in entries if r["pit_quote"]]
    def band_key(x):
        return "|".join((
            x["category"], str(x["section"]),
            "p" + value_band(x["probability"], (.7, .75, .8, .85, .9)),
            "o" + value_band(x["odds"], (1.5, 1.7, 1.8, 2.0)),
            "d" + value_band(x["depth"], (.75, .8, .9)),
        ))
    return {
        "schema": 1, "status": "INDEPENDENT_CANONICAL_ISSUED_SETTLEMENT_AUDIT",
        "scope": "PUBLIC_ISSUED_TOP_VALUE_MATCH_WINNER_ONLY",
        "raw_issued_publication_rows": raw_pubs,
        "exact_canonical_settled_unique": len(entries),
        "quote_time_proven_issued_unique": len(verified),
        "rejected_or_unverified_counts_nonexclusive": rejected,
        "canonical_verified": {
            "overall": aggregate(entries),
            "by_category": groups(entries, lambda x: x["category"]),
            "by_section": groups(entries, lambda x: x["section"]),
            "by_model": groups(entries, lambda x: x["model"]),
            "by_date": by_date,
            "by_category_section": groups(entries, lambda x: x["category"] + "|" + x["section"]),
        },
        "pit_quote_proven": {
            "overall": aggregate(verified),
            "by_category": groups(verified, lambda x: x["category"]),
            "by_section": groups(verified, lambda x: x["section"]),
            "by_category_probability_odds_depth": groups(verified, band_key),
        },
        "interpretation_limits": [
            "Actual public issuance evidence is required; selector candidates are excluded.",
            "Completed canonical outcome must exactly agree with graded issued result, both players, tour and date.",
            "Quote timestamps absent/invalid are excluded from PIT-proven subgroup, not imagined.",
            "Category uses only frozen issuance-time tournament context, not hindsight canonical level.",
            "Historical categories and small samples are descriptive, not optimized production rules.",
            "Profit/ROI assumes genuine frozen Match Winner odds and flat 1u stake.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--canonical", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--prediction-before", type=Path)
    parser.add_argument("--prediction-after", type=Path)
    args = parser.parse_args()
    if args.prediction_before or args.prediction_after:
        if not (args.prediction_before and args.prediction_after):
            parser.error("both release pin files required")
        verify_pins(args.prediction_before, args.prediction_after,
                    [args.ledger.name], args.ledger.parent, require_manifest=True)
    import pandas as pd
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    if not isinstance(ledger, list):
        raise ValueError("invalid ledger schema")
    cols = ["match_id", "player1_id", "player2_id", "winner_id", "status",
            "scheduled_at", "tour", "provider_context_json"]
    canonical = pd.read_parquet(args.canonical, columns=cols).to_dict("records")
    report = audit(ledger, canonical)
    report["source_sha256"] = {
        "ledger": hashlib.sha256(args.ledger.read_bytes()).hexdigest(),
        "canonical": hashlib.sha256(args.canonical.read_bytes()).hexdigest(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "raw_issued": report["raw_issued_publication_rows"],
        "exact_verified": report["exact_canonical_settled_unique"],
        "pit_proven": report["quote_time_proven_issued_unique"],
        "overall": report["canonical_verified"]["overall"],
        "by_category": report["canonical_verified"]["by_category"],
        "rejections": report["rejected_or_unverified_counts_nonexclusive"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
