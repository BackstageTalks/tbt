#!/usr/bin/env python3
"""Read-only MoviOdds batch preparation for the EXISTING guarded CDB writer.

Source fetch consumes protected Azure FINAL records, never tennis provider
quota; link/combination produce the same import_offline_linked_serve_return
stage expected by the existing cdb-drive-inbox guarded release pipeline.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path

from moviodds_cdb_format import format_cdb_archive, verify_cdb_archive


def _dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                            for row in rows), encoding="utf-8")


def fetch_dates(out_dir: Path, days_back: int, *, base_url: str, token: str,
                today: datetime | None = None) -> dict:
    """Read provider-backed FINAL source safely; 503 denotes unverifiable day."""
    import requests
    from moviodds_drive_archive import fetch_daily_final, _json_bytes

    if not 1 <= days_back <= 7:
        raise ValueError("Unsupported retrospective scope (1..7)")
    if not base_url.startswith("https://") or not token:
        raise ValueError("Protected MoviOdds export credentials missing")
    now = (today or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source_dir = out_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    available, unavailable = [], []
    for i in range(1, days_back + 1):
        day = (now - timedelta(days=i)).date().isoformat()
        try:
            original = fetch_daily_final(date_utc=day, base_url=base_url, token=token)
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 503:
                raise
            unavailable.append({"date_utc": day, "reason": "source_final_scan_unavailable_503"})
            print("MOVIODDS_CDB_DAY_UNAVAILABLE", day, flush=True)
            continue
        converted = format_cdb_archive(original)
        verify_cdb_archive(converted)
        if original["count"] != converted["count"]:
            raise ValueError("Source record loss")
        file = source_dir / f"moviodds-{day}.json"
        file.write_bytes(_json_bytes(converted))
        verify_cdb_archive(json.loads(file.read_bytes()))
        available.append({"date_utc": day, "count": converted["count"],
                          "sha256": sha256(file.read_bytes()).hexdigest()})
        print("MOVIODDS_CDB_DAY_VERIFIED", day, converted["count"], flush=True)
    if not available:
        raise ValueError("No verified source days: abort rather than report false success")
    report = {
        "schema": 1, "source": "moviodds", "normalized": available,
        "counts": {"normalized_rows": sum(item["count"] for item in available)},
        "unavailable": unavailable,
        "cdb_values_written": 0, "cdb_mutated": False,
    }
    _dump(out_dir / "report.json", report)
    return report


def combine_stages(source_dir: Path, stage_root: Path, out_dir: Path) -> dict:
    """Cross-day de-duplicate and quarantine ambiguous canonical associations."""
    source_report = json.loads((source_dir / "report.json").read_text(encoding="utf-8"))
    if source_report.get("source") != "moviodds":
        raise ValueError("Unexpected source report")
    expected = {item["date_utc"] for item in source_report["normalized"]}
    if not expected or len(expected) != len(source_report["normalized"]):
        raise ValueError("Source dates missing or duplicated")
    actual = {p.name for p in stage_root.iterdir() if p.is_dir()}
    if actual != expected:
        raise ValueError("Missing or extra linked source date")
    staged, review, original_count = [], [], 0
    source_ids = set()
    for day in sorted(expected):
        folder = stage_root / day
        daily = json.loads((folder / "report.json").read_text(encoding="utf-8"))
        if daily.get("source") != "moviodds":
            raise ValueError("Non-MoviOdds link report")
        rows = [json.loads(s) for s in (folder / "eligible.jsonl").read_text(encoding="utf-8").splitlines() if s]
        rejected = [json.loads(s) for s in (folder / "review.jsonl").read_text(encoding="utf-8").splitlines() if s]
        if daily["raw"] != len(rows) + len(rejected) or daily["raw"] != next(
                x["count"] for x in source_report["normalized"] if x["date_utc"] == day):
            raise ValueError("Daily raw/source row conservation failed")
        original_count += daily["raw"]
        for row in rows:
            proof = row["provenance"][0]
            if proof.get("source") != "moviodds" or not proof.get("source_sha256"):
                raise ValueError("Invalid provider provenance")
            sid = str(proof["source_fixture_id"])
            if sid in source_ids:
                raise ValueError("Source fixture repeated across UTC days")
            source_ids.add(sid)
            # Prevent a known pre-existing cell from being declared a new
            # value. The existing importer is NULL-only in both dry-run/write.
            if not row.get("incoming_stats") or any(
                    row.get("baseline_stats", {}).get(k) is not None
                    for k in row["incoming_stats"]):
                raise ValueError("Stage includes non-NULL or empty incoming values")
            staged.append(row)
        review.extend(rejected)
    grouped = Counter(x["match_id"] for x in staged)
    duplicates = {k for k, n in grouped.items() if n > 1}
    ready = []
    for row in staged:
        if row["match_id"] in duplicates:
            review.append({
                "source": "moviodds", "reason": "cross_day_ambiguous_canonical_identity",
                "match_id": row["match_id"],
                "source_fixture_id": row["provenance"][0]["source_fixture_id"],
            })
        else:
            ready.append(row)
    if original_count != len(ready) + len(review):
        raise ValueError("Cross-day raw row conservation failed")
    ready.sort(key=lambda x: x["match_id"])
    review.sort(key=lambda x: (str(x.get("source_fixture_id")), str(x.get("reason"))))
    _jsonl(out_dir / "eligible.jsonl", ready)
    _jsonl(out_dir / "review.jsonl", review)
    report = {
        "schema": 1, "source": "moviodds", "raw": original_count,
        "eligible_matches": len(ready),
        "eligible_new_values": sum(len(row["incoming_stats"]) for row in ready),
        "filtered_matches": len(review),
        "conflict_matches": sum("conflict" in str(x.get("reason")) for x in review),
        "cross_day_ambiguous": len(duplicates),
        "verified_days": sorted(expected),
        "unavailable_days": source_report["unavailable"],
        "cdb_values_written": 0, "production_mutated": False,
    }
    _dump(out_dir / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="operation", required=True)
    first = sub.add_parser("fetch")
    first.add_argument("--out-dir", type=Path, required=True)
    first.add_argument("--days-back", type=int, required=True)
    second = sub.add_parser("combine")
    second.add_argument("--source-dir", type=Path, required=True)
    second.add_argument("--stage-root", type=Path, required=True)
    second.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "fetch":
        import os
        report = fetch_dates(args.out_dir, args.days_back,
                             base_url=os.environ["BLINQ_BASE_URL"],
                             token=os.environ["BLINQ_LIVE_WORKER_TOKEN"])
    else:
        report = combine_stages(args.source_dir, args.stage_root, args.out_dir)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
