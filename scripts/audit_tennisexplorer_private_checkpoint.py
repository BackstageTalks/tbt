#!/usr/bin/env python3
"""Read-only byte-pinned QA for TennisExplorer category/year checkpoints.

Never re-fetch a website, link CDB identities, infer historical odds timing,
publish canonical observations or enable model features.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
from hashlib import sha256
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
from collections import Counter


CATEGORIES = {"atp-single", "atp-double", "wta-single", "wta-double"}
MAX_MEMBERS = 20000
MAX_MEMBER_BYTES = 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024


def _rows(tar, entry, *, jsonl=False):
    member = tar.extractfile(entry)
    if member is None:
        raise ValueError("Archive member unreadable")
    with member, io.TextIOWrapper(member, encoding="utf-8-sig", errors="strict", newline="") as stream:
        if jsonl:
            for line in stream:
                if line.strip():
                    yield json.loads(line)
        else:
            yield from csv.DictReader(stream)


def _json(tar, entry):
    member = tar.extractfile(entry)
    if member is None:
        raise ValueError("Archive JSON member unreadable")
    with member:
        return json.load(member)


def audit(path: Path, category: str, year: int, expected_sha256: str) -> dict:
    if category not in CATEGORIES or not (1998 <= year <= 2026):
        raise ValueError("Unsupported TennisExplorer year/category")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ValueError("Invalid pinned SHA-256")
    hash_ = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hash_.update(chunk)
    actual_sha = hash_.hexdigest()
    if actual_sha != expected_sha256:
        raise ValueError("SOURCE_SHA256_MISMATCH")
    root = f"data/tennisexplorer/"
    results = root + f"results/{category}/{year}"
    enrich = root + f"enrichment/{category}/{year}"
    counts = Counter()
    issues = []
    with tarfile.open(path, "r:gz") as tar:
        members = tar.getmembers()
        if len(members) > MAX_MEMBERS:
            raise ValueError("Unsafe archive member count")
        names = set()
        total = 0
        for m in members:
            name = m.name
            parts = PurePosixPath(name)
            if parts.is_absolute() or ".." in parts.parts or "\\" in name:
                raise ValueError("Unsafe archive member path")
            if not m.isfile() or m.issym() or m.islnk():
                raise ValueError("Unsafe archive member type")
            if name in names:
                raise ValueError("Duplicate archive member path")
            names.add(name)
            total += m.size
            if m.size > MAX_MEMBER_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError("Unsafe archive expanded bytes")
            if not (name.startswith(root + f"results/{category}/{year}.")
                    or name.startswith(root + f"enrichment/{category}/{year}.")):
                raise ValueError("Unexpected source category/year in archive")
        by_name = {m.name: m for m in members}
        csv_name = results + ".csv"
        page_name = results + ".pages.csv"
        result_meta = results + ".run_metadata.json"
        details_name = enrich + ".jsonl"
        detail_meta = enrich + ".run_metadata.json"
        for mandatory in (csv_name, page_name, result_meta):
            if mandatory not in by_name:
                issues.append("MISSING_" + PurePosixPath(mandatory).name)

        results_keys = set()
        result_ids = set()
        if csv_name in by_name:
            for row in _rows(tar, by_name[csv_name]):
                counts["result_rows"] += 1
                if not isinstance(row, dict):
                    counts["invalid_result_rows"] += 1
                    continue
                day = str(row.get("date") or "")
                mid = str(row.get("match_id") or "").strip()
                try:
                    valid_date = date.fromisoformat(day).year == year
                except ValueError:
                    valid_date = False
                if not valid_date:
                    counts["invalid_match_year"] += 1
                if mid:
                    key = (day, mid)
                    if key in results_keys:
                        counts["duplicate_result_event_ids"] += 1
                    results_keys.add(key)
                    result_ids.add(mid)
                else:
                    counts["results_missing_match_id"] += 1
                if row.get("category") not in (category, None, ""):
                    counts["cross_category_result_rows"] += 1

        ok_days = set()
        if page_name in by_name:
            for row in _rows(tar, by_name[page_name]):
                counts["page_audit_rows"] += 1
                if row.get("status") == "ok":
                    day = str(row.get("date") or "")
                    try:
                        if date.fromisoformat(day).year == year:
                            ok_days.add(day)
                        else:
                            counts["page_wrong_year"] += 1
                    except ValueError:
                        counts["page_bad_date"] += 1
        expected_days = (date(year + 1, 1, 1) - date(year, 1, 1)).days
        counts["expected_days"] = expected_days
        counts["unique_successful_days"] = len(ok_days)
        counts["missing_successful_days"] = expected_days - len(ok_days)
        if result_meta in by_name:
            meta = _json(tar, by_name[result_meta])
            if not isinstance(meta, dict) or meta.get("category") != category or meta.get("year") != year:
                issues.append("RESULT_METADATA_CONTRADICTS_ASSET")
            elif (meta.get("complete") is not True or
                  meta.get("expected_days") != expected_days or
                  meta.get("completed_days") != len(ok_days) or
                  meta.get("missing_days_count") != expected_days - len(ok_days)):
                issues.append("RESULT_COMPLETENESS_UNPROVEN")

        detail_ids = set()
        if details_name in by_name:
            for row in _rows(tar, by_name[details_name], jsonl=True):
                counts["detail_rows"] += 1
                if not isinstance(row, dict) or row.get("source") != "TennisExplorer":
                    counts["invalid_details"] += 1
                    continue
                mid = str(row.get("match_id") or "").strip()
                if not mid:
                    counts["details_missing_id"] += 1
                elif mid in detail_ids:
                    counts["duplicate_detail_ids"] += 1
                elif mid not in result_ids:
                    counts["unmatched_detail_ids"] += 1
                detail_ids.add(mid)
        if detail_meta in by_name:
            meta = _json(tar, by_name[detail_meta])
            if not isinstance(meta, dict) or meta.get("category") != category or meta.get("year") != year:
                issues.append("DETAIL_METADATA_CONTRADICTS_ASSET")
            elif meta.get("complete") is not True:
                issues.append("DETAIL_COMPLETENESS_UNPROVEN")
        else:
            issues.append("MISSING_DETAIL_COMPLETENESS_EVIDENCE")
        if details_name not in by_name:
            issues.append("MISSING_DETAIL_ROWS")

        counts["unique_result_ids"] = len(result_ids)
        counts["unique_detail_ids"] = len(detail_ids)
        counts["result_ids_without_details"] = len(result_ids - detail_ids)
        hard_errors = [k for k in (
            "invalid_result_rows", "invalid_match_year", "duplicate_result_event_ids",
            "cross_category_result_rows", "page_wrong_year", "page_bad_date",
            "invalid_details", "details_missing_id", "duplicate_detail_ids",
            "unmatched_detail_ids") if counts[k]]
        if counts["missing_successful_days"]:
            issues.append("INCOMPLETE_DAILY_SOURCE_COVERAGE")
        issues += hard_errors
        result_issues = {
            "invalid_result_rows", "invalid_match_year",
            "duplicate_result_event_ids", "cross_category_result_rows",
            "page_wrong_year", "page_bad_date"
        }
        detail_issues = {
            "invalid_details", "details_missing_id", "duplicate_detail_ids",
            "unmatched_detail_ids"
        }
        results_complete = (
            counts["result_rows"] > 0
            and all(name in by_name for name in (csv_name, page_name, result_meta))
            and counts["missing_successful_days"] == 0
            and not any(counts[k] for k in result_issues)
            and not any(x.startswith("RESULT_") for x in issues)
        )
        details_complete = (
            results_complete
            and details_name in by_name and detail_meta in by_name
            and counts["result_ids_without_details"] == 0
            and not any(counts[k] for k in detail_issues)
            and not any("DETAIL_" in x for x in issues)
        )
        # A missing details ledger cannot invalidate 366 independently
        # accounted-for daily result pages. Keep the two feature families apart.
        status = (
            "RESULTS_INCOMPLETE_QUARANTINE_NO_CDB" if not results_complete else
            "SOURCE_STRUCTURALLY_COMPLETE_CDB_LINK_PENDING" if details_complete else
            "RESULTS_COMPLETE_DETAILS_PARTIAL_NO_CDB"
        )
    return {
        "schema": 1, "source": "TennisExplorer", "category": category, "year": year,
        "asset": path.name, "raw_sha256_verified": actual_sha,
        "status": status, "counts": dict(sorted(counts.items())),
        "results_source_state": (
            "COMPLETE_SOURCE_SCOPED_RESULTS_PENDING_CDB_LINK_AND_RIGHTS"
            if results_complete else "INCOMPLETE_QUARANTINED"
        ),
        "details_source_state": (
            "COMPLETE_SOURCE_SCOPED_DETAILS_PENDING_CDB_LINK_AND_RIGHTS"
            if details_complete else "PARTIAL_DETAILS_QUARANTINED"
        ),
        "result_rows_eligible_for_further_source_scoped_review": (
            counts["result_rows"] if results_complete else 0
        ),
        "issues": sorted(set(issues)), "canonical_identity_verified": False,
        "doubles_team_identity_verified": False,
        "market_quote_timestamp_verified": False,
        "source_use_rights_verified": False,
        "canonical_cell_delta_approved": 0,
        "production_cdb_modified": False, "model_training_or_promotion": False,
        "policy": "Only historical source observations; rankings and odds not assumed to be available before match",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--asset", type=Path, required=True)
    p.add_argument("--category", choices=sorted(CATEGORIES), required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--expected-sha256", required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    result = audit(args.asset, args.category, args.year, args.expected_sha256)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("TENNISEXPLORER_CHECKPOINT_QA", json.dumps(result, sort_keys=True))
    if result["results_source_state"] != "COMPLETE_SOURCE_SCOPED_RESULTS_PENDING_CDB_LINK_AND_RIGHTS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
