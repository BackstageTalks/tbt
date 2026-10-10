"""Exact-cell canonical 2023 Wimbledon stats writer; local only.

The sole remote publication path is the separately gated GitHub workflow.
Do not infer missing zero, overwrite existing values, or change unstaged rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_manifest, update_year_manifest
from audit_wimbledon_2023_cdb_stage import sha256

YEAR = 2023
ALLOWED = {"p1_aces", "p2_aces", "p1_double_faults", "p2_double_faults"}
SOURCE_SHA = "19507e156e6ff307027d39e44000ac446a564f87b3c8d59a5225dc6d1674c512"


def read_stage(path: Path, audit: Path):
    report = json.loads(audit.read_text(encoding="utf-8"))
    if report.get("schema") != 1 or report.get("status") != "read_only_classified":
        raise ValueError("Unverified source stage report")
    if report.get("production_mutated") is not False or report.get("model_promoted") is not False:
        raise ValueError("Stage has production/model side effects")
    if report.get("source_sha256") != SOURCE_SHA or int(report.get("cdb_year") or 0) != YEAR:
        raise ValueError("Stage source/year differs from pinned import")
    records = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(records) != report.get("observation_rows") or len(records) != 20:
        raise ValueError("Stage missing reviewed Wimbledon field rows")
    counts = {}
    for row in records:
        state = row["validation"]["state"]
        counts[state] = counts.get(state, 0) + 1
    if counts.get("CONFLICT", 0) or counts.get("UNRESOLVED", 0):
        raise ValueError("Source conflict/incompleteness must be quarantined, not written")
    if counts.get("READY_MISSING", 0) != 12 or counts.get("ALREADY_PRESENT", 0) != 8:
        raise ValueError("Unexpected staged cardinality; requires separate source review")
    if any(counts.get(k, 0) != report.get("counts", {}).get(k, 0)
           for k in ("READY_MISSING", "ALREADY_PRESENT", "CONFLICT", "UNRESOLVED")):
        raise ValueError("Stage counts disagree with audit")
    return records, report


def _count(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean count")
    number = float(value)
    if not number.is_integer() or number < 0 or number > 200:
        raise ValueError("Invalid canonical/incoming count")
    return int(number)


def patch(before: pd.DataFrame, records: list[dict], *, baseline_sha: str):
    required = {"match_id", "tour", "scheduled_at", "player1_id", "player2_id",
                "player1_name", "player2_name", "stats_json", "winner_id",
                "tournament", "best_of", "provider_context_json"}
    if not required.issubset(before.columns):
        raise ValueError("Canonical parquet missing required columns")
    ids = before["match_id"].astype(str)
    if ids.duplicated().any():
        raise ValueError("Duplicate canonical match IDs")
    by_id = dict(zip(ids, before.index))
    target = before.copy(deep=True)
    seen, ready, already = set(), 0, 0
    patched_ids = set()
    for rec in records:
        mid = str(rec.get("canonical_match_id") or "")
        field = rec.get("field")
        state = rec.get("validation", {}).get("state")
        k = (mid, field)
        if not mid or field not in ALLOWED or k in seen:
            raise ValueError("Missing, unauthorized or duplicate canonical stage field")
        seen.add(k)
        if rec.get("contract_version") != "1.0.0" or rec.get("scope") != "whole_match":
            raise ValueError("Unapproved source granularity")
        if rec.get("source_id") != "figshare_wimbledon_2023_momentum":
            raise ValueError("Unknown raw source")
        if rec["source_version"]["content_sha256"] != SOURCE_SHA:
            raise ValueError("Source version not pinned")
        if rec["validation"]["validated_against_cdb_sha256"] != baseline_sha:
            raise ValueError("Stale canonical stage")
        if rec.get("canonical_match_id") not in by_id:
            raise ValueError("Canonical match missing")
        before_row = before.loc[by_id[mid]]
        if str(before_row["tour"]).lower() != "wta":
            raise ValueError("Unexpected canonical tour")
        if pd.Timestamp(before_row["scheduled_at"]).year != YEAR:
            raise ValueError("Canonical year mismatch")
        orientation = rec.get("player_orientation") or {}
        side = 1 if field.startswith("p1_") else 2
        name = str(before_row[f"player{side}_name"])
        if orientation.get("canonical_subject") != name or orientation.get("relation") not in ("same", "reversed"):
            raise ValueError("Canonical side identity missing or reversed incorrectly")
        if bool(orientation.get("swapped")) != (orientation.get("relation") == "reversed"):
            raise ValueError("Inconsistent source side/orientation evidence")
        source_identity = rec.get("source_identity") or {}
        source_name = source_identity.get("original_player2" if orientation["swapped"] == (side == 1)
                                         else "original_player1")
        if orientation.get("source_subject") != source_name:
            raise ValueError("Source side identity changed")
        try:
            source_stats = json.loads(before_row["stats_json"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Malformed canonical stats") from exc
        if not isinstance(source_stats, dict):
            raise ValueError("Canonical stats must be object")
        baseline = _count(source_stats.get(field))
        expected = rec["validation"]["expected_original_value"]
        if _count(expected) != baseline:
            raise ValueError("Canonical original cell changed")
        observed = _count(rec["value"])
        if observed is None or state not in ("READY_MISSING", "ALREADY_PRESENT"):
            raise ValueError("Missing data or unapproved observation")
        if state == "READY_MISSING":
            if baseline is not None or rec.get("import_eligibility") != "candidate_after_package_review":
                raise ValueError("Attempted overwrite or unapproved write")
            source_stats[field] = observed
            target.at[by_id[mid], "stats_json"] = json.dumps(
                source_stats, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            ready += 1
            patched_ids.add(mid)
        else:
            if baseline != observed:
                raise ValueError("Existing CDB value disagrees with source")
            already += 1
    if len(seen) != 20 or len(patched_ids) != 3 or ready != 12 or already != 8:
        raise ValueError("Unexpected verified field/match count")
    columns = [x for x in before.columns if x != "stats_json"]
    pd.testing.assert_frame_equal(before[columns], target[columns], check_dtype=True)
    for idx in before.index:
        orig = json.loads(before.at[idx, "stats_json"])
        next_stats = json.loads(target.at[idx, "stats_json"])
        if idx not in {by_id[x] for x in patched_ids}:
            if orig != next_stats:
                raise ValueError("Unstaged canonical stats changed")
        else:
            changed = {k for k in orig.keys() | next_stats.keys()
                       if orig.get(k) != next_stats.get(k)}
            expected_changed = {r["field"] for r in records
                                if r["canonical_match_id"] == str(before.at[idx, "match_id"])
                                and r["validation"]["state"] == "READY_MISSING"}
            if changed != expected_changed:
                raise ValueError("Patched match has extra canonical stats changes")
    return target, {"canonical_rows": len(before), "updated_matches": len(patched_ids),
                    "rank_fields_modified": 0, "stats_fields_added": ready,
                    "existing_stats_overwritten": 0, "changed_years": [YEAR]}


def canonical_year(directory: Path):
    file = directory / f"history-{YEAR}.parquet"
    manifest = load_manifest(directory)
    meta = (manifest.get("years") or {}).get(str(YEAR)) or {}
    if not file.is_file() or not meta or meta.get("sha256") != sha256(file):
        raise ValueError("Pinned current year partition or manifest invalid")
    return file, meta["sha256"]


def run(mode: str, before_dir: Path, stage_file: Path, stage_report: Path,
        after_dir: Path, report_file: Path):
    before_file, baseline = canonical_year(before_dir)
    records, audit = read_stage(stage_file, stage_report)
    if audit["cdb_partition_sha256"] != baseline:
        raise ValueError("Source audit is stale to latest CDB")
    source = pd.read_parquet(before_file, engine="pyarrow")
    expected, counts = patch(source, records, baseline_sha=baseline)
    target_file = after_dir / before_file.name
    if mode == "write":
        if target_file.resolve() == before_file.resolve():
            raise ValueError("Cannot write over downloaded immutable CDB")
        after_dir.mkdir(parents=True, exist_ok=True)
        temporary = target_file.with_suffix(".parquet.proof.tmp")
        try:
            expected.to_parquet(temporary, engine="pyarrow", compression="zstd", index=False)
            actual = pd.read_parquet(temporary, engine="pyarrow")
            pd.testing.assert_frame_equal(expected, actual, check_dtype=True)
            temporary.replace(target_file)
        finally:
            if temporary.exists():
                temporary.unlink()
        update_year_manifest(after_dir, YEAR, {"sha256": sha256(target_file),
                              "bytes": target_file.stat().st_size, "rows": len(expected)})
        status = "verified_local_write"
    elif mode == "verify":
        actual = pd.read_parquet(target_file, engine="pyarrow")
        pd.testing.assert_frame_equal(expected, actual, check_dtype=True)
        status = "verified"
    elif mode == "dry-run":
        status = "verified_dry_run"
    else:
        raise ValueError("Unrecognized mode")
    report = {"schema": 1, "status": status, "mode": mode, **counts,
              "before_partition_sha256": baseline,
              "after_partition_sha256": sha256(target_file) if mode in ("write", "verify") else None,
              "production_mutated": False, "model_training_performed": False,
              "model_promoted": False, "provider_api_requests": 0}
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("dry-run", "write", "verify"), required=True)
    parser.add_argument("--before-dir", type=Path, required=True)
    parser.add_argument("--after-dir", type=Path, required=True)
    parser.add_argument("--stage-file", type=Path, required=True)
    parser.add_argument("--stage-report", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    run(args.mode, args.before_dir, args.stage_file, args.stage_report, args.after_dir, args.report)


if __name__ == "__main__":
    main()
