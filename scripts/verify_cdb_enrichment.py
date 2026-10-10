"""Fail-closed verification for ATP/Futures/Charting enrichment of existing CDB matches.

This module never writes a canonical DB or publishes a release. It verifies the
offline linker's dry-run and independently downloaded post-write partitions.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


REJECT_COUNTS = (
    "identity_missing", "identity_changed", "invalid_stats", "stat_conflicts",
    "invalid_provenance", "provenance_conflicts", "invalid_delayed_observation",
    "baseline_stats_changed", "no_stats",
)


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Not an object: {path}")
    return payload


def staged_entries(path: Path) -> dict[str, dict]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if not isinstance(entry, dict) or entry.get("schema") != 1 or entry.get("import_ready") is not True:
            raise ValueError("Invalid staged row")
        mid = str(entry.get("match_id") or "")
        incoming = entry.get("incoming_stats")
        if not mid or mid in result or not isinstance(incoming, dict) or not incoming or entry.get("delayed_observation") is not None:
            raise ValueError("Duplicate/missing match or unexpected non-stat payload")
        if not isinstance(entry.get("canonical"), dict):
            raise ValueError("Staged identity signature missing")
        if any(not k.startswith(("p1_", "p2_")) or isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) for k, v in incoming.items()):
            raise ValueError("Invalid staged statistic")
        result[mid] = entry
    return result


def check_reports(link: dict, dry: dict, stage: dict, write: dict | None = None) -> int:
    if link.get("production_mutated") is not False or dry.get("production_mutated") is not False:
        raise ValueError("Unexpected production mutation")
    if link.get("api_requests") != 0 or dry.get("api_requests") != 0:
        raise ValueError("Unexpected provider requests")
    if link.get("canonical_rows") is None or not isinstance(link["canonical_rows"], int):
        raise ValueError("Missing canonical baseline")
    counts = dry.get("counts")
    if not isinstance(counts, dict):
        raise ValueError("Invalid dry run")
    for key in REJECT_COUNTS:
        if counts.get(key, 0):
            raise ValueError(f"Fail-closed importer: {key}={counts[key]}")
    if len(stage) != dry.get("stage_rows"):
        raise ValueError("Stage count mismatch")
    link_counts = link.get("counts")
    if not isinstance(link_counts, dict):
        raise ValueError("Missing linker evidence")
    # The linker omits staged_matches when it links only already-present
    # observations. This is a verified no-op, not a failed partial import.
    linked = link_counts.get("staged_matches", 0)
    if not isinstance(linked, int) or linked < len(stage):
        raise ValueError("Linker stage baseline mismatch")
    if linked != len(stage) and len(stage) != 0:
        raise ValueError("Partial linker/importer stage mismatch")
    if not stage and not (isinstance(link_counts.get("already_present"), int)
                          and link_counts["already_present"] > 0
                          and isinstance(link_counts.get("identity_linked"), int)
                          and link_counts["identity_linked"] > 0):
        raise ValueError("Missing corroborated zero-delta linker evidence")
    updated = counts.get("updated", 0)
    if not isinstance(updated, int) or updated < 0 or updated > len(stage):
        raise ValueError("Unsafe updated count")
    if not isinstance(dry.get("quality_ready_before"), int) or not isinstance(dry.get("quality_ready_after"), int):
        raise ValueError("Missing quality baseline")
    if dry["quality_ready_after"] < dry["quality_ready_before"]:
        raise ValueError("Quality regression")
    if dry.get("quality_ready_added") != dry["quality_ready_after"] - dry["quality_ready_before"]:
        raise ValueError("Inconsistent quality delta")
    years = dry.get("changed_years")
    if not isinstance(years, list) or years != sorted(set(years)) or any(not isinstance(y, int) or y < 1990 or y > 2100 for y in years):
        raise ValueError("Invalid changed partitions")
    if bool(updated) != bool(years):
        raise ValueError("Updated rows and partitions disagree")
    if write is not None:
        if write.get("production_mutated") is not False or write.get("counts") != counts:
            raise ValueError("Write/dry-run mismatch")
        for key in ("stage_rows", "changed_years", "quality_ready_after", "quality_ready_before", "quality_ready_added"):
            if write.get(key) != dry.get(key):
                raise ValueError(f"Write/dry-run {key} mismatch")
        if bool(write.get("local_partitions_written")) != bool(updated):
            raise ValueError("Local write not confirmed")
    return updated


def _record(record) -> dict:
    if hasattr(record, "model_dump"):
        return record.model_dump(mode="json")
    if hasattr(record, "dict"):
        return record.dict()
    if isinstance(record, dict):
        return record
    raise ValueError("Unrecognized canonical record")


def verify_partition_records(original, persisted, stage: dict) -> set[str]:
    before = {str(r.match_id): _record(r) for r in original}
    after = {str(r.match_id): _record(r) for r in persisted}
    if len(before) != len(original) or len(after) != len(persisted) or before.keys() != after.keys():
        raise ValueError("Canonical row count or match identity changed")
    modified = set()
    for mid, old in before.items():
        new = after[mid]
        entry = stage.get(mid)
        if entry is None:
            if new != old:
                raise ValueError(f"Unstaged canonical record changed: {mid}")
            continue
        clean_before = {k: v for k, v in old.items() if k != "stats"}
        clean_after = {k: v for k, v in new.items() if k != "stats"}
        if clean_before != clean_after:
            raise ValueError(f"Immutable canonical fields changed: {mid}")
        previous_stats = old.get("stats") or {}
        current_stats = new.get("stats") or {}
        if not isinstance(previous_stats, dict) or not isinstance(current_stats, dict):
            raise ValueError("Invalid stored statistics")
        allowed = entry["incoming_stats"]
        if any(k not in previous_stats or previous_stats[k] is None for k in allowed):
            if old == new:
                raise ValueError(f"Intended enrichment missing: {mid}")
            modified.add(mid)
        unexpected = set(current_stats) - set(previous_stats) - set(allowed)
        if unexpected or any(current_stats.get(k) != v for k, v in previous_stats.items() if v is not None):
            raise ValueError(f"Existing stats changed: {mid}")
        for key, value in allowed.items():
            if current_stats.get(key) is None or not math.isclose(float(current_stats[key]), float(value), rel_tol=0, abs_tol=1e-6):
                raise ValueError(f"Staged field does not match persisted value: {mid}/{key}")
    return modified


def verify_readback(backup: Path, persisted: Path, stage: dict, dry: dict) -> dict:
    from tbt.data.history_snapshot import load_snapshot
    matched = set()
    for year in dry["changed_years"]:
        source = backup / f"history-{year}.parquet"
        target = persisted / source.name
        if not source.is_file() or not target.is_file():
            raise ValueError(f"Missing prewrite/readback partition for {year}")
        found = verify_partition_records(load_snapshot(source), load_snapshot(target), stage)
        if found & matched:
            raise ValueError("Same match present across year partitions")
        matched.update(found)
    if len(matched) != dry["counts"].get("updated", 0):
        raise ValueError("Number of verified enriched matches differs from write")
    return {"persisted_enriched_matches": len(matched), "changed_years": dry["changed_years"], "canonical_rows_added": 0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("dry", "write", "readback"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root
    stage = staged_entries(root / "link/auto_linked.jsonl")
    dry = read_json(root / "dry-run/report.json")
    link = read_json(root / "link/report.json")
    write = read_json(root / "write/report.json") if args.phase in ("write", "readback") else None
    changed = check_reports(link, dry, stage, write)
    result = {"phase": args.phase, "updated": changed, "quality_ready_added": dry["quality_ready_added"], "canonical_rows_added": 0}
    if args.phase == "readback":
        result.update(verify_readback(root / "backup", root / "verify", stage, dry))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
