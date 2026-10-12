#!/usr/bin/env python3
"""Verified, additive-only writer for the pinned 2025/2026 user-uploaded tennis batch.

The source-to-canonical linker is independent. This module NEVER selects identities.
It only consumes linker output with full canonical identity signatures, and refuses
to modify any non-NULL canonical values or unrelated rows. Local-only; publication
must be handled by an external globally locked, SHA-CAS release workflow.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


def valid_stats(values: object) -> dict[str, float]:
    from import_offline_linked_serve_return import ALLOWED, COUNT_FIELDS
    if not isinstance(values, dict) or not values or not set(values) <= ALLOWED:
        raise ValueError("Unsupported or empty canonical statistic set")
    clean = {}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Invalid statistic value type")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("Nonfinite statistic")
        field = key.split("_", 1)[1]
        if field in COUNT_FIELDS:
            if numeric < 0 or not numeric.is_integer() or numeric > 100:
                raise ValueError("Invalid count statistic")
        elif not 0 <= numeric <= 1:
            raise ValueError("Invalid rate statistic")
        clean[key] = numeric
    return clean


def records(stage_path: Path) -> dict[str, dict]:
    rows = {}
    for line in stage_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        mid = str(row.get("match_id") or "")
        src = row.get("source") or {}
        proof_method = src.get("verification")
        accepted_methods = {
            "exact_provider_event_native_player_ids_utc_winner_verified_score",
            "flashscore_exact_event_clock_four_counts_full_two_set_score",
        }
        if proof_method not in accepted_methods:
            raise ValueError("Unattested source-to-canonical match proof")
        if proof_method == "flashscore_exact_event_clock_four_counts_full_two_set_score":
            expected_flags = {"three_way_exact_utc", "native_event_exact",
                              "full_two_set_score", "four_existing_stat_counts",
                              "canonical_winner_id", "two_player_sides"}
            evidence = src.get("proof")
            if (src.get("flashscore_index_sha256") !=
                  "328f9c36c0f4021c745ca7119ea904a4ae7cadb66cee17cc63f2ca6f5774a952"
                    or not isinstance(evidence, dict)
                    or any(evidence.get(flag) is not True for flag in expected_flags)):
                raise ValueError("Missing pinned independent Flashscore source proof")
        if (not mid or mid in rows or row.get("schema") != 1
                or row.get("import_ready") is not True
                or not isinstance(row.get("canonical"), dict)
                or row.get("delayed_observation") is not None):
            raise ValueError("Invalid, duplicate, or nonattested staged identity")
        valid_stats(row.get("incoming_stats"))
        rows[mid] = row
    return rows


def apply(stage_path: Path, before_dir: Path, after_dir: Path, report_path: Path) -> dict:
    from tbt.data.history_snapshot import load_snapshot, partition_path
    from import_offline_linked_serve_return import _signature
    from offline_exact_cdb_write import write_exact_stats_partition, verify_persisted

    staged = records(stage_path)
    if not staged:
        raise ValueError("Refusing empty write stage")
    by_year = defaultdict(set)
    touched = set()
    patches = []
    # Every original year partition must be copied byte-for-byte into after_dir
    # before invoking this function.
    for year in (2024, 2025, 2026):
        before_file = partition_path(before_dir, year)
        after_file = partition_path(after_dir, year)
        if before_file.read_bytes() != after_file.read_bytes():
            raise ValueError("Working CDB differs from exact prewrite baseline")
        match_rows = load_snapshot(after_file)
        lookup = {str(m.match_id): m for m in match_rows}
        if len(lookup) != len(match_rows):
            raise ValueError("Duplicate canonical ID in current year")
        selected = set(lookup) & set(staged)
        for mid in selected:
            m = lookup[mid]
            row = staged[mid]
            if _signature(m) != row["canonical"]:
                raise ValueError("Stage signature differs from current canonical match")
            patch = valid_stats(row["incoming_stats"])
            existing = dict(m.stats or {})
            if any(existing.get(k) is not None for k in patch):
                raise ValueError("Attempted overwrite of existing canonical statistic")
            m.stats = {**existing, **patch}
            by_year[year].add(mid)
            touched.add(mid)
        if selected:
            result = write_exact_stats_partition(after_dir, year, match_rows, selected)
            patches.append(result)
    if touched != set(staged):
        raise ValueError("Staged match missing from exact canonical partition or wrong year")
    result = verify_persisted(before_dir, after_dir, list(staged.values()), sorted(by_year))
    if result["enriched_matches"] != len(staged):
        raise ValueError("Local persisted match count does not equal stage")
    if result["added_values"] != sum(len(r["incoming_stats"]) for r in staged.values()):
        raise ValueError("Local persisted cell count does not equal stage")
    result.update({"per_year": patches, "source_stage_rows": len(staged),
                   "publish_completed": False})
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--before", type=Path, required=True)
    p.add_argument("--after", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(apply(args.stage, args.before, args.after, args.report),
                     sort_keys=True))


if __name__ == "__main__":
    main()
