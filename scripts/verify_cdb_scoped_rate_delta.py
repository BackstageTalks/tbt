#!/usr/bin/env python3
"""Read-only full-CDB integrity readback without deserializing unchanged years.

Every untouched year is SHA-256 byte-identical; every match in every changed
year is compared using the existing exact opponent-rate readback verifier.
Only the existing guarded writer can publish the staged NULL-only fields.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from tbt.data.history_snapshot import load_manifest, load_partitions
from recover_cdb_opponent_service_rates import verify_readback


def _sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink() or not path.stat().st_size:
        raise ValueError(f"Missing/unsafe CDB partition: {path.name}")
    h = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _inventory(directory: Path) -> tuple[dict[int, dict], int]:
    manifest = load_manifest(directory)
    items = manifest.get("years")
    if not isinstance(items, dict) or not items:
        raise ValueError("Missing canonical history manifest/year inventory")
    years = {}
    total = 0
    for key, row in items.items():
        if not isinstance(row, dict) or not str(key).isdigit():
            raise ValueError("Invalid canonical year metadata")
        year = int(key)
        name = f"history-{year:04d}.parquet"
        if str(row.get("asset") or name) != name:
            raise ValueError("Canonical year filename mismatch")
        digest = row.get("sha256")
        count = row.get("rows")
        if not isinstance(digest, str) or not re.fullmatch("[a-f0-9]{64}", digest):
            raise ValueError("Missing canonical year SHA-256")
        if type(count) is not int or count <= 0:
            raise ValueError("Invalid canonical year row count")
        if _sha256(directory / name) != digest:
            raise ValueError(f"Canonical year file digest differs from manifest: {year}")
        years[year] = row
        total += count
    actual = {p.name for p in directory.glob("history-*.parquet")}
    expected = {f"history-{year:04d}.parquet" for year in years}
    if actual != expected:
        raise ValueError("Canonical partition inventory changed")
    return years, total


def verify_scoped(before_dir: Path, after_dir: Path, stage_file: Path) -> dict:
    before_dir, after_dir, stage_file = Path(before_dir), Path(after_dir), Path(stage_file)
    stage = [json.loads(s) for s in stage_file.read_text(encoding="utf-8").splitlines() if s.strip()]
    if not stage:
        raise ValueError("Empty staged CDB additions")
    if len({row.get("match_id") for row in stage}) != len(stage):
        raise ValueError("Duplicate or missing staged match identity")
    changed_years = sorted({row.get("utc_year") for row in stage})
    if not all(type(y) is int and 1949 <= y <= 2100 for y in changed_years):
        raise ValueError("Invalid staged canonical years")

    original, before_total = _inventory(before_dir)
    persisted, after_total = _inventory(after_dir)
    if original.keys() != persisted.keys() or before_total != after_total:
        raise ValueError("Canonical year inventory/total row count changed")
    if not set(changed_years).issubset(original):
        raise ValueError("Staged year missing from canonical manifest")
    for year in original:
        if original[year]["rows"] != persisted[year]["rows"]:
            raise ValueError(f"Canonical partition row count changed: {year}")
        if year not in changed_years and original[year] != persisted[year]:
            raise ValueError(f"Untouched year metadata changed: {year}")

    before = load_partitions(before_dir, years=changed_years)
    after = load_partitions(after_dir, years=changed_years)
    stage_ids = {str(row["match_id"]) for row in stage}
    if not stage_ids.issubset({str(match.match_id) for match in before}):
        raise ValueError("Staged match absent from changed year(s)")

    result = verify_readback(before, after, stage)
    changed_count = result["canonical_matches"]
    expected_changed_count = sum(original[year]["rows"] for year in changed_years)
    if result["status"] != "verified" or changed_count != expected_changed_count:
        raise ValueError("Changed-year exact record count mismatch")
    return {
        **result,
        "canonical_matches": before_total,
        "changed_year_matches_checked": changed_count,
        "changed_years": changed_years,
        "untouched_partition_hashes_verified": len(original) - len(changed_years),
        "canonical_year_partitions_verified": len(original),
        "all_canonical_rows_verified_by_exact_record_or_sha256": before_total,
        "manifest_inventory_verified": True,
        "provider_requests": 0,
        "production_mutated": False,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--before-dir", required=True, type=Path)
    p.add_argument("--after-dir", required=True, type=Path)
    p.add_argument("--stage-file", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    result = verify_scoped(a.before_dir, a.after_dir, a.stage_file)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("CDB_SCOPED_COMPLETE_READBACK", json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
