from __future__ import annotations

import argparse
import hashlib
import json
from datetime import timezone
from pathlib import Path

from _bootstrap import ROOT
from tbt.data.history_snapshot import (
    list_partition_years,
    load_manifest,
    load_partitions,
    load_snapshot,
    partition_path,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Integrity-check private GitHub yearly history partitions. Optionally prove "
            "that every match_id from the old monolithic snapshot is still present."
        )
    )
    parser.add_argument("--history-dir", default=str(ROOT / ".cache" / "tbt" / "history"))
    parser.add_argument("--legacy-snapshot", default=None)
    args = parser.parse_args()

    directory = Path(args.history_dir)
    manifest = load_manifest(directory)
    years = list_partition_years(directory)
    if not years:
        raise SystemExit("No history partitions found")
    if not manifest:
        raise SystemExit("history_manifest.json is missing")

    failures: list[str] = []
    rows_total = 0
    seen_match_ids: set[str] = set()
    duplicate_match_ids: list[str] = []
    details: dict[str, object] = {}

    manifest_years = manifest.get("years") if isinstance(manifest.get("years"), dict) else {}
    for year in years:
        path = partition_path(directory, year)
        matches = load_snapshot(path)
        rows_total += len(matches)
        bad_year = [m.match_id for m in matches if m.scheduled_at.astimezone(timezone.utc).year != year]
        if bad_year:
            failures.append(f"{year}: {len(bad_year)} rows are outside partition year")

        for match in matches:
            key = str(match.match_id)
            if key in seen_match_ids:
                duplicate_match_ids.append(key)
            seen_match_ids.add(key)

        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entry = manifest_years.get(str(year), {}) if isinstance(manifest_years, dict) else {}
        expected_sha = str(entry.get("sha256") or "") if isinstance(entry, dict) else ""
        expected_rows = entry.get("rows") if isinstance(entry, dict) else None
        if expected_sha and expected_sha != digest:
            failures.append(f"{year}: sha256 mismatch")
        if expected_rows is not None and int(expected_rows) != len(matches):
            failures.append(f"{year}: manifest rows={expected_rows}, actual={len(matches)}")

        details[str(year)] = {
            "rows": len(matches),
            "sha256": digest,
            "coverage_status": entry.get("coverage_status") if isinstance(entry, dict) else None,
            "history_start": entry.get("history_start") if isinstance(entry, dict) else None,
            "history_end": entry.get("history_end") if isinstance(entry, dict) else None,
        }

    if duplicate_match_ids:
        failures.append(f"cross-partition duplicate match_id count={len(set(duplicate_match_ids))}")

    legacy_report = None
    if args.legacy_snapshot:
        legacy_path = Path(args.legacy_snapshot)
        if not legacy_path.is_file():
            failures.append(f"legacy snapshot not found: {legacy_path}")
        else:
            legacy = load_snapshot(legacy_path)
            legacy_ids = {str(match.match_id) for match in legacy}
            missing = sorted(legacy_ids - seen_match_ids)
            legacy_report = {
                "rows": len(legacy),
                "unique_match_ids": len(legacy_ids),
                "covered_match_ids": len(legacy_ids) - len(missing),
                "missing_match_ids": len(missing),
                "missing_examples": missing[:20],
            }
            if missing:
                failures.append(
                    f"legacy snapshot coverage failed: {len(missing)} match_ids are missing"
                )

    report = {
        "ok": not failures,
        "partition_years": years,
        "rows_total": rows_total,
        "years": details,
        "legacy_snapshot_coverage": legacy_report,
        "source_updated_at_max": manifest.get("source_updated_at_max"),
        "failures": failures,
        "completeness_note": (
            "Integrity validation proves file/hash/year consistency and, when supplied, "
            "lossless coverage of the old GitHub snapshot. Provider completeness is a "
            "separate question and may be improved later with direct GH backfills."
        ),
        "supabase_full_history_read": False,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
