#!/usr/bin/env python3
"""Read-only, privacy-preserving missing-stat coverage map of private canonical CDB.

Each released partition MUST first pass cdb_wta_verified_window SHA checks.
No match identities, names, source payloads or per-match stats leave the runner.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import timezone
import json
from pathlib import Path

FIELDS = (
    "aces", "double_faults", "first_serve_win", "second_serve_win",
    "service_points_won", "return_points_won", "break_point_serve_win",
    "break_point_return_win", "first_strike_serve_win", "return_in_play_rate",
    "return_deep_rate", "net_points_win", "attacking_points_rate",
    "unforced_error_rate",
)
CORE = ("service_points_won", "return_points_won")
SUPPORTED_YEARS = set(range(2016, 2027))


def coverage(matches) -> dict:
    """Aggregate statuses only; never retain any match-level identity or values."""
    slots = defaultdict(lambda: {
        "matches": 0,
        "core_complete_matches": 0,
        "core_fully_missing_matches": 0,
        "fields": {
            field: {"present_cells": 0, "missing_cells": 0,
                    "both_present_matches": 0, "both_missing_matches": 0}
            for field in FIELDS
        },
    })
    seen = set()
    total = 0
    for match in matches:
        match_id = str(match.match_id)
        if not match_id or match_id in seen:
            raise ValueError("Missing or duplicate canonical match identity")
        seen.add(match_id)
        year = match.scheduled_at.astimezone(timezone.utc).year
        tour = str(match.tour or "").lower()
        if year not in SUPPORTED_YEARS or tour not in {"atp", "wta"}:
            raise ValueError("Unexpected year or tour in bounded canonical snapshot")
        values = match.stats
        if values is None:
            values = {}
        if not isinstance(values, dict):
            raise ValueError("Canonical stats are not a JSON object")
        slot = slots[(year, tour)]
        slot["matches"] += 1
        total += 1
        core = [values.get(f"{side}_{field}") is not None
                for field in CORE for side in ("p1", "p2")]
        if all(core):
            slot["core_complete_matches"] += 1
        if not any(core):
            slot["core_fully_missing_matches"] += 1
        for field in FIELDS:
            p1 = values.get("p1_" + field) is not None
            p2 = values.get("p2_" + field) is not None
            item = slot["fields"][field]
            item["present_cells"] += int(p1) + int(p2)
            item["missing_cells"] += int(not p1) + int(not p2)
            item["both_present_matches"] += int(p1 and p2)
            item["both_missing_matches"] += int(not p1 and not p2)
    table = []
    for (year, tour), item in sorted(slots.items()):
        table.append({"year": year, "tour": tour, **item})
    return {
        "schema": 1,
        "state": "CDB_GAP_AUDIT_READ_ONLY",
        "production_mutated": False, "api_requests": 0,
        "canonical_rows": total, "year_tour": table,
        "note": "Counts of presently missing canonical cells only; not validated source additions.",
    }


def run(history_dir: Path, output: Path, *, expected_provider_quarantine: int = 0) -> dict:
    from _bootstrap import ROOT  # noqa: F401
    from tbt.data.history_snapshot import load_partitions
    from tbt.data.history_safety import sanitize_history_identities
    from recover_cdb_opponent_service_rates import verified_provider_collision_quarantine
    if output.exists():
        raise ValueError("Output report already exists")
    original = load_partitions(history_dir)
    matches, safety = sanitize_history_identities(original)
    isolated = int(safety.get("quarantined_rows") or 0)
    if isolated or safety.get("changed"):
        if not verified_provider_collision_quarantine(safety, expected_provider_quarantine):
            raise ValueError("Canonical identity quarantine differs from pinned provider collision; fail closed")
    elif expected_provider_quarantine:
        raise ValueError("Expected provider-ID quarantine disappeared; repeat full identity audit")
    if len(original) != len(matches) + isolated:
        raise ValueError("CDB raw/safe row conservation failed")
    report = coverage(matches)
    report["canonical_raw_rows"] = len(original)
    report["excluded_ambiguous_provider_rows"] = isolated
    report["identity_policy"] = "read_only_exact_provider_collision_quarantine"
    if report["canonical_rows"] + isolated != report["canonical_raw_rows"]:
        raise ValueError("CDB aggregate report row conservation failed")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--history-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--expected-provider-quarantine", type=int, default=0,
                   help="Exact known 2026 provider-ID collision rows to exclude in this read-only census")
    args = p.parse_args()
    result = run(args.history_dir, args.output,
                 expected_provider_quarantine=args.expected_provider_quarantine)
    print(json.dumps({"state": result["state"], "canonical_rows": result["canonical_rows"],
                      "canonical_raw_rows": result["canonical_raw_rows"],
                      "excluded_ambiguous_provider_rows": result["excluded_ambiguous_provider_rows"],
                      "year_tour_groups": len(result["year_tour"]),
                      "production_mutated": False, "api_requests": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
