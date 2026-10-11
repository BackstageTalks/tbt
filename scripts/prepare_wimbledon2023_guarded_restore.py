"""Strict one-time request and manifest gate for restoring five lost 2023 rows.

No API calls, no release writes. The GitHub Actions writer separately owns the
global writer lease, immutable prewrite backup, last-moment CAS and full reread.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from audit_wimbledon2023_recovery_readonly import BACKUP, BACKUP_SHA, TARGET_IDS, sha256

CURRENT_SHA = "25202f79e5e4c8bcdc728ca5b35fa1e47d6238233e336d1b69fa2e2ac2648284"
EXPECTED_OLD_ROWS = 107760
EXPECTED_NEW_ROWS = 107765
YEAR = "2023"
PARTITION = "history-2023.parquet"
MANIFEST = "history_manifest.json"
BUNDLE = "_tbt_bundle_manifest.json"
GATES = (
    "require_global_lock",
    "require_immutable_prewrite_backup",
    "require_fresh_release_CAS",
    "require_independent_full_year_remote_readback",
    "require_no_preexisting_cell_overwrite",
    "require_exact_source_match_ids",
)


def validate_request(value: dict) -> dict:
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("Invalid pinned one-time restore request")
    expected = {
        "mode": "write_exact_five_2023_only",
        "source_release": BACKUP,
        "source_year_sha256": BACKUP_SHA,
        "expected_current_year_sha256": CURRENT_SHA,
        "year": 2023,
        "expected_current_rows": EXPECTED_OLD_ROWS,
        "expected_restored_rows": EXPECTED_NEW_ROWS,
        "expected_new_match_ids": sorted(TARGET_IDS),
        "provider_api_requests": 0,
        "train_model": False,
        "promote_model": False,
        "create_cron": False,
        "overwrite_current_nonnull": False,
    }
    for key, expect in expected.items():
        if value.get(key) != expect or type(value.get(key)) is not type(expect):
            raise ValueError(f"Unsafe or unpinned restore request key {key}")
    for key in GATES:
        if value.get(key) is not True:
            raise ValueError(f"Missing mandatory writer guard {key}")
    if set(value) != {"schema"} | set(expected) | set(GATES):
        raise ValueError("Unexpected restore request keys")
    return value


def verify_release_inputs(folder: Path, request: dict) -> dict:
    """Prove all current year/manifest/bundle bytes match before publication."""
    validate_request(request)
    year_path = folder / PARTITION
    manifest_path = folder / MANIFEST
    bundle_path = folder / BUNDLE
    before = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    years = before.get("years") or {}
    if len(years) != 78 or YEAR not in years:
        raise ValueError("Canonical manifest inventory incomplete")
    entry = years[YEAR]
    if int(entry.get("rows") or 0) != EXPECTED_OLD_ROWS:
        raise ValueError("Unrecognized original 2023 row count")
    year_sha = sha256(year_path)
    if year_sha != CURRENT_SHA or entry.get("sha256") != year_sha:
        raise ValueError("Current 2023 SHA pin or annual manifest changed")
    files = bundle.get("files") or {}
    for filename in (PARTITION, MANIFEST):
        if files.get(filename, {}).get("sha256") != sha256(folder / filename):
            raise ValueError(f"Committed bundle mismatch for {filename}")
    if int(entry.get("bytes") or 0) != year_path.stat().st_size:
        raise ValueError("Canonical 2023 byte size mismatch")
    if sum(int(x["rows"]) for x in years.values()) != 994096:
        raise ValueError("Canonical row-count baseline changed")
    return {"current_year_sha256": year_sha, "current_manifest_sha256": sha256(manifest_path),
            "current_bundle_sha256": sha256(bundle_path), "current_year_rows": EXPECTED_OLD_ROWS,
            "manifest_year_count": 78}


def prepare_updated_manifest(before_dir: Path, proposed_year: Path,
                             out: Path, request: dict) -> dict:
    validate_request(request)
    metadata = verify_release_inputs(before_dir, request)
    import pandas as pd
    before = json.loads((before_dir / MANIFEST).read_text(encoding="utf-8"))
    year_hash = sha256(proposed_year)
    final = pd.read_parquet(proposed_year, engine="pyarrow")
    if len(final) != EXPECTED_NEW_ROWS or final["match_id"].duplicated().any():
        raise ValueError("Prepared parquet is not exactly 107765 unique matches")
    if not TARGET_IDS <= set(final["match_id"].astype(str)):
        raise ValueError("Prepared year is missing one or more pinned rows")
    new_manifest = copy.deepcopy(before)
    year = new_manifest["years"][YEAR]
    year["rows"] = EXPECTED_NEW_ROWS
    year["sha256"] = year_hash
    year["bytes"] = proposed_year.stat().st_size
    new_manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    # No revision to any other year or manifest policy.
    if new_manifest["years"] | {YEAR: before["years"][YEAR]} != before["years"]:
        raise ValueError("Unrelated annual manifest changed")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(new_manifest, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    reread = json.loads(out.read_text(encoding="utf-8"))
    if reread["years"][YEAR]["sha256"] != year_hash:
        raise ValueError("New year metadata did not persist")
    if sum(int(x["rows"]) for x in reread["years"].values()) != 994101:
        raise ValueError("Output manifest unexpected global row count")
    return {"status": "LOCAL_FIVE_ROW_MANIFEST_PREPARED_NO_UPLOAD",
            "prior": metadata,
            "new_year_sha256": year_hash,
            "new_manifest_sha256": sha256(out),
            "total_canonical_rows_after": 994101,
            "other_77_year_entries_unchanged": True,
            "production_mutated": False, "provider_api_requests": 0}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--before-dir", type=Path)
    p.add_argument("--proposed-year", type=Path)
    p.add_argument("--output-manifest", type=Path)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    request = validate_request(json.loads(args.request.read_text(encoding="utf-8")))
    if args.before_dir and args.proposed_year and args.output_manifest:
        result = prepare_updated_manifest(args.before_dir, args.proposed_year,
                                          args.output_manifest, request)
    elif not any((args.before_dir, args.proposed_year, args.output_manifest)):
        result = {"status": "GUARDED_ONE_TIME_RESTORE_REQUEST_VALIDATED_NO_WRITE",
                  "source_sha256": BACKUP_SHA,
                  "current_year_sha256": CURRENT_SHA,
                  "new_rows": 5,
                  "production_mutated": False}
    else:
        raise SystemExit("Incomplete restore manifest preparation arguments")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("WIMBLEDON2023_GUARDED_REQUEST", json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
