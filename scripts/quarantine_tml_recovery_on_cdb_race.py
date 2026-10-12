#!/usr/bin/env python3
"""Fail-closed private research-archive gate when canonical CDB races.

This NEVER authorizes a CDB or model write. On a changed CDB manifest the
only publishable output is an explicitly quarantined source-native recovery
queue, provided that zero three-way canonical witnesses exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for part in iter(lambda: src.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def guard(original: Path, fresh: Path, report_dir: Path) -> dict:
    for p in (original, fresh, report_dir / "report.json",
              report_dir / "private-native-id-recovery-queue.jsonl",
              report_dir / "private-three-way-candidates.jsonl"):
        if p.is_symlink() or not p.is_file():
            raise ValueError(f"Missing or symbolic-link evidence: {p.name}")
    before, after = sha(original), sha(fresh)
    report_path = report_dir / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (report.get("status") != "THREE_WAY_OFFICIAL_ATP_READ_ONLY"
        or report.get("ready_for_cdb_write") != 0 or report.get("cdb_writes") != 0
        or report.get("model_trained") is not False
        or report.get("api_requests") != 0):
        raise ValueError("Read-only original review contract failed")
    qfile = report_dir / "private-native-id-recovery-queue.jsonl"
    qbytes = qfile.read_bytes()
    if hashlib.sha256(qbytes).hexdigest() != report.get("native_id_recovery_queue_sha256"):
        raise ValueError("Private native-ID recovery queue SHA mismatch")
    records = [json.loads(line) for line in qbytes.splitlines() if line.strip()]
    if len(records) != report.get("counts", {}).get("private_native_id_recovery_candidates"):
        raise ValueError("Queue cardinality mismatch")
    for row in records:
        if (row.get("schema") != 1 or row.get("canonical_match_id") is not None
            or row.get("official_identity_verified") is not False
            or row.get("import_ready") is not False
            or row.get("write_authorized") is not False
            or row.get("model_feature_allowed") is not False
            or row.get("reason") not in {
                "SYNTHETIC_LISTING_ID_REQUIRES_OFFICIAL_NATIVE_MATCH",
                "NATIVE_MATCH_ID_OFFICIAL_SET_COUNT_MISMATCH",
                "NATIVE_MATCH_ID_REQUIRES_FULL_INDEPENDENT_SCORE_REVIEW"}):
            raise ValueError("Invalid or preauthorized research row")
    current = before == after
    if not current:
        if (report.get("counts", {}).get("three_way_official_review_candidates") != 0
            or (report_dir / "private-three-way-candidates.jsonl").read_bytes().strip()):
            raise ValueError("Changed CDB cannot publish previous canonical witnesses")
    report["canonical_manifest_sha256_at_download"] = before
    report["canonical_manifest_sha256_at_archive_gate"] = after
    report["canonical_snapshot_current_at_archive_gate"] = current
    report["archive_status"] = (
        "CURRENT_READ_ONLY_RESEARCH_SNAPSHOT" if current
        else "STALE_CDB_SOURCE_ONLY_RECOVERY_QUARANTINE"
    )
    report["ready_for_cdb_write"] = 0
    report["cdb_writes"] = 0
    report["import_ready"] = False
    report["write_authorized"] = False
    report["model_feature_allowed"] = False
    tmp = report_path.with_name(report_path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, report_path)
    finally:
        tmp.unlink(missing_ok=True)
    return {"archive_status": report["archive_status"],
            "source_only_queue": len(records),
            "cdb_writes": 0,
            "ready_for_cdb_write": 0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-manifest", type=Path, required=True)
    parser.add_argument("--fresh-manifest", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(guard(args.original_manifest, args.fresh_manifest, args.report_dir),
                     sort_keys=True))


if __name__ == "__main__":
    main()
