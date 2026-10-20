#!/usr/bin/env python3
"""Aggregate private WTA CDB source conflicts without exporting match identities.

This is a diagnostic, not a conflict-resolution or import mechanism. No
majority voting, tolerance-based rescue, source precedence or CDB writes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path


def summarize(quarantine: Path) -> dict:
    if not quarantine.is_file():
        raise ValueError("Required private quarantine missing")
    conflicts = Counter()
    fields = Counter()
    identity_evidence = Counter()
    delta_buckets = Counter()
    matches = 0
    total = 0
    strong_identity = 0
    for line in quarantine.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not str(row.get("match_id") or ""):
            raise ValueError("Invalid private quarantine row")
        matches += 1
        proofs = row.get("sources") or []
        if not isinstance(proofs, list):
            raise ValueError("Invalid source identity evidence")
        strong = bool(proofs)
        for proof in proofs:
            evidence = proof.get("evidence") if isinstance(proof, dict) else None
            if not isinstance(evidence, list):
                raise ValueError("Invalid source identity evidence list")
            observed = set(str(x) for x in evidence)
            strong = strong and {
                "date_exact", "tournament_exact", "winner", "surface",
            }.issubset(observed)
            for item in observed:
                if item in {"date_exact", "date_plusminus_1", "date_tournament_window",
                            "tournament_exact", "tournament_tokens", "winner",
                            "surface", "round", "round_conflict", "surface_conflict",
                            "best_of_conflict"}:
                    identity_evidence[item] += 1
        strong_identity += int(strong)
        for conflict in row.get("conflicts") or []:
            if not isinstance(conflict, dict):
                raise ValueError("Invalid conflicting statistic")
            reason = str(conflict.get("reason") or "unknown")
            conflicts[reason] += 1
            key = str(conflict.get("key") or "")
            # Aggregated canonical field names only, never source/player IDs.
            if not key.startswith(("p1_", "p2_")):
                continue
            suffix = key[3:]
            if suffix not in {
                "aces", "double_faults", "first_serve_win", "second_serve_win",
                "service_points_won", "return_points_won",
                "break_point_serve_win", "break_point_return_win",
                "first_strike_serve_win", "return_in_play_rate",
                "return_deep_rate", "net_points_win",
                "attacking_points_rate", "unforced_error_rate",
            }:
                continue
            fields[suffix] += 1
            total += 1
            try:
                existing, incoming = float(conflict["existing"]), float(conflict["incoming"])
            except (ValueError, TypeError, KeyError):
                delta_buckets["unquantifiable"] += 1
                continue
            if not math.isfinite(existing) or not math.isfinite(incoming):
                delta_buckets["unquantifiable"] += 1
                continue
            distance = abs(existing - incoming)
            if distance <= 1e-6:
                delta_buckets["tiny"] += 1
            elif distance <= 0.01:
                delta_buckets["up_to_0_01"] += 1
            elif distance <= 0.05:
                delta_buckets["up_to_0_05"] += 1
            elif distance <= 0.25:
                delta_buckets["up_to_0_25"] += 1
            else:
                delta_buckets["over_0_25"] += 1
    return {
        "schema": 1, "state": "CDB_WTA_CONFLICTS_REQUIRE_INDEPENDENT_REVIEW",
        "production_mutated": False, "api_requests": 0,
        "quarantined_matches": matches,
        "strong_identity_but_conflicting_stats_matches": strong_identity,
        "canonical_fields_with_observed_conflicts": total,
        "conflict_reasons": dict(sorted(conflicts.items())),
        "stat_field_conflicts": dict(sorted(fields.items())),
        "identity_evidence_counts": dict(sorted(identity_evidence.items())),
        "absolute_difference_buckets": dict(sorted(delta_buckets.items())),
        "note": "No staged or imported values; conflicting cells remain quarantined.",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quarantine", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError("Refusing to overwrite previous diagnostic")
    report = summarize(args.quarantine)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({"quarantined_matches": report["quarantined_matches"],
                      "strong_conflicted_matches":
                      report["strong_identity_but_conflicting_stats_matches"],
                      "production_mutated": False}, sort_keys=True))


if __name__ == "__main__":
    main()
