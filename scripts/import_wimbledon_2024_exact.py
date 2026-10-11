"""Strict local Wimbledon 2024 exact-cell delta application and full-year readback.

The publication workflow owns the global writer lock, immutable backup and
private remote release. This script never publishes to a remote or trains.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_manifest, update_year_manifest
from stage_wimbledon_2024_cdb import MATCH_SHA, POINT_SHA, YEAR, digest

ALLOWED = {f"p{side}_{name}" for side in (1, 2) for name in
           ("aces", "double_faults", "unforced_errors", "net_points", "net_points_won")}


def _validated_stage(stage_file, stage_report, original_sha):
    report = json.loads(Path(stage_report).read_text())
    if (report.get("schema") != 1 or report.get("status") != "prepared_for_isolated_replay"
            or report.get("write_performed") is not False or report.get("model_trained") is not False
            or report.get("year") != YEAR or report.get("cdb_sha256") != original_sha
            or report.get("match_sha256") != MATCH_SHA or report.get("points_sha256") != POINT_SHA
            or report.get("stage_sha256") != digest(stage_file)
            or report.get("stage_has_conflicts") is not False):
        raise ValueError("Unverified, conflicting or stale Wimbledon source stage")
    items = [json.loads(line) for line in Path(stage_file).read_text().splitlines() if line.strip()]
    seen = set()
    for item in items:
        mid = str(item.get("match_id") or "")
        additions = item.get("additions")
        expected = item.get("expected_identity")
        if (not mid or mid in seen or item.get("schema") != 1 or item.get("year") != YEAR
                or item.get("source") != "wimbledon_2024_raw_match_and_point_csv"
                or item.get("cdb_sha256") != original_sha or item.get("match_sha256") != MATCH_SHA
                or item.get("points_sha256") != POINT_SHA or not isinstance(expected, dict)
                or expected.get("match_id") != mid or not isinstance(additions, dict)
                or not additions or not set(additions).issubset(ALLOWED)
                or sorted(additions) != item.get("expected_original_null_fields")
                or item.get("model_eligibility") != "postmatch_only"
                or item.get("available_at") is not None):
            raise ValueError("Untrusted staged match, field or point-in-time semantics")
        for value in additions.values():
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
                raise ValueError("Invalid staged count")
        seen.add(mid)
    if len(items) != report.get("counts", {}).get("staged_matches"):
        raise ValueError("Stage cardinality mismatch")
    if sum(len(row["additions"]) for row in items) != report.get("counts", {}).get("staged_fields"):
        raise ValueError("Stage field count mismatch")
    return items, report


def _year_frame(directory):
    directory = Path(directory)
    path = directory / f"history-{YEAR}.parquet"
    meta = (load_manifest(directory).get("years") or {}).get(str(YEAR)) or {}
    if meta.get("sha256") != digest(path) or meta.get("asset") != path.name:
        raise ValueError("Canonical yearly Parquet/manifest hash mismatch")
    frame = pd.read_parquet(path)
    if int(meta.get("rows", -1)) != len(frame):
        raise ValueError("Canonical yearly row count changed")
    if "match_id" not in frame or "stats_json" not in frame:
        raise ValueError("Canonical year columns missing")
    ids = frame["match_id"].astype(str)
    if ids.duplicated().any() or (ids == "").any():
        raise ValueError("Duplicate canonical IDs")
    return frame, meta


def _patch(frame, stage):
    ids = dict(zip(frame["match_id"].astype(str), frame.index))
    expected = frame.copy(deep=True)
    changed = {}
    for record in stage:
        mid = record["match_id"]
        if mid not in ids:
            raise ValueError("Staged match missing from CDB")
        pos = ids[mid]
        row = frame.loc[pos]
        for key, value in record["expected_identity"].items():
            if key not in frame.columns or str(row[key]) != value:
                raise ValueError("Canonical identity/context drift: " + mid + " " + key)
        original = json.loads(row["stats_json"])
        if not isinstance(original, dict):
            raise ValueError("Invalid original stats JSON")
        patched = dict(original)
        for key, value in record["additions"].items():
            if key in original and original[key] is not None:
                raise ValueError("Forbidden non-null CDB overwrite: " + key)
            patched[key] = value
        expected.at[pos, "stats_json"] = json.dumps(patched, sort_keys=True,
                                                       separators=(",", ":"), ensure_ascii=False,
                                                       allow_nan=False)
        changed[mid] = record["additions"]
    columns = [c for c in frame.columns if c != "stats_json"]
    pd.testing.assert_frame_equal(frame[columns], expected[columns], check_dtype=True)
    unaffected = ~frame.index.isin([ids[mid] for mid in changed])
    pd.testing.assert_series_equal(frame.loc[unaffected, "stats_json"],
                                   expected.loc[unaffected, "stats_json"])
    return expected, changed


def run(mode, before_dir, after_dir, stage_file, stage_report):
    if mode not in ("dry-run", "write", "verify"):
        raise ValueError("Invalid import mode")
    before_dir, after_dir = Path(before_dir), Path(after_dir)
    before, meta = _year_frame(before_dir)
    stage, report = _validated_stage(stage_file, stage_report, meta["sha256"])
    expected, delta = _patch(before, stage)
    if mode == "write":
        if not delta:
            raise ValueError("Zero-delta canonical write forbidden")
        if before_dir.resolve() == after_dir.resolve():
            raise ValueError("In-place update forbidden")
        after_dir.mkdir(parents=True, exist_ok=True)
        target = after_dir / f"history-{YEAR}.parquet"
        tmp = target.with_name(target.name + ".tmp")
        try:
            expected.to_parquet(tmp, compression="zstd", engine="pyarrow", index=False)
            read = pd.read_parquet(tmp)
            pd.testing.assert_frame_equal(read, expected, check_dtype=True)
            tmp.replace(target)
            update_year_manifest(after_dir, YEAR, {
                "sha256": digest(target), "bytes": target.stat().st_size, "rows": len(before)
            })
        finally:
            if tmp.exists():
                tmp.unlink()
    elif mode == "verify":
        actual, _ = _year_frame(after_dir)
        pd.testing.assert_frame_equal(actual, expected, check_dtype=True)
    return {
        "schema": 1, "status": "verified" if mode == "verify" else "verified_" + mode,
        "year": YEAR, "canonical_rows_checked": len(before), "changed_matches": len(delta),
        "added_values": sum(len(x) for x in delta.values()), "existing_values_overwritten": 0,
        "before_sha256": meta["sha256"],
        "after_sha256": digest(after_dir / f"history-{YEAR}.parquet") if mode != "dry-run" else None,
        "source_stage_sha256": digest(stage_file),
        "production_mutated": False, "model_trained": False, "model_promoted": False,
        "provider_api_requests": 0,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("dry-run", "write", "verify"), required=True)
    for key in ("before_dir", "after_dir", "stage_file", "stage_report", "out"):
        p.add_argument("--" + key.replace("_", "-"), required=True, type=Path)
    args = p.parse_args()
    result = run(args.mode, args.before_dir, args.after_dir, args.stage_file, args.stage_report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
