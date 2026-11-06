"""Read-only post-restoration proof of the CURRENT 78-year canonical CDB.

Reuses the existing checksum-verified canonical download and the exact frozen
1 Nov source/prewrite backups. Never stages a writer, modifies CDB, reserves
TennisAPI/PropLine or logs private identities and row data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from restore_cdb_2026_lossless import (
    BACKUP, OLD_FILE, OLD_SHA, REPO, TAG, assets, command, download,
    index, release, sha, stamp,
)

PREWRITE = "blinq-cdb2026-lossless-prewrite-41310504634-1"
PREWRITE_MANIFEST_SHA = "4f2a7c944f63cb227337d77fe5663f49b9f7a7c272845f49028e45016a679aa9"
EXPECTED_BACKUP = 98994
EXPECTED_PREWRITE = 2927
EXPECTED_OVERLAP = 1258
EXPECTED_OLD_ONLY = 97736
EXPECTED_PREWRITE_ONLY = 1669
EXPECTED_MERGED_MIN = 100663
YEARS = frozenset(range(1949, 2027))


def _stats(table, row: int) -> dict:
    value = table["stats_json"][row].as_py()
    data = json.loads(value or "{}")
    if not isinstance(data, dict):
        raise ValueError("Malformed canonical stat evidence")
    return data


def compare_lineage(old, prewrite, current, *,
                    expected_backup=EXPECTED_BACKUP,
                    expected_prewrite=EXPECTED_PREWRITE,
                    expected_overlap=EXPECTED_OVERLAP,
                    expected_old_only=EXPECTED_OLD_ONLY,
                    expected_prewrite_only=EXPECTED_PREWRITE_ONLY,
                    expected_min=EXPECTED_MERGED_MIN) -> dict:
    """Prove the exact old and 1 Nov prewrite identities survived subsequent jobs.

    Overlap in the two originals uses prewrite/current precedence; original
    backup-only rows use the pinned backup. Do not resurrect conflicting values.
    """
    older = index(old, "immutable_source")
    before = index(prewrite, "prewrite_backup")
    live = index(current, "current")
    prior_overlap = set(older) & set(before)
    older_only = set(older) - set(before)
    before_only = set(before) - set(older)
    if (len(older) != expected_backup or len(before) != expected_prewrite
            or len(prior_overlap) != expected_overlap
            or len(older_only) != expected_old_only
            or len(before_only) != expected_prewrite_only):
        raise ValueError("Original pinned lineage does not match recorded 1 Nov cohorts")
    missing_backup = set(older) - set(live)
    missing_prewrite = set(before) - set(live)
    if missing_backup or missing_prewrite or len(live) < expected_min:
        raise ValueError("Current CDB missing restored or prewrite 2026 identities: "
                         + json.dumps({
                             "backup_missing": len(missing_backup),
                             "prewrite_missing": len(missing_prewrite),
                             "current_rows": len(live),
                             "minimum": expected_min,
                         }, sort_keys=True))

    identity_conflicts = missing_stats = modified_stats = 0
    preserved_cells = 0
    # Original prewrite/current rows have precedence over the backup in
    # overlapping cases. Backup-only records were appended unchanged.
    sources = ((prewrite, before, set(before)),
               (old, older, older_only))
    for source, source_index, matches in sources:
        for mid in matches:
            i, j = source_index[mid], live[mid]
            if any(source[k][i].as_py() != current[k][j].as_py()
                   for k in ("player1_id", "player2_id", "scheduled_at")):
                identity_conflicts += 1
            original_stats = _stats(source, i)
            current_stats = _stats(current, j)
            for field, value in original_stats.items():
                if value is None:
                    continue
                preserved_cells += 1
                if current_stats.get(field) is None:
                    missing_stats += 1
                elif current_stats[field] != value:
                    modified_stats += 1

    counts = {
        "source_backup_2026_rows": len(older),
        "source_prewrite_2026_rows": len(before),
        "original_2026_overlap": len(prior_overlap),
        "backup_only_restored_and_still_present": len(older_only),
        "prewrite_only_still_present": len(before_only),
        "current_2026_rows": len(live),
        "post_restore_net_new_2026_rows": len(set(live) - (set(older) | set(before))),
        "source_nonnull_cells_checked": preserved_cells,
        "missing_original_nonnull_cells": missing_stats,
        "modified_original_nonnull_cells": modified_stats,
        "historical_identity_conflicts": identity_conflicts,
        "missing_backup_match_ids": len(missing_backup),
        "missing_prewrite_match_ids": len(missing_prewrite),
    }
    if identity_conflicts or missing_stats or modified_stats:
        raise ValueError("Current CDB 2026 conservation failure: "
                         + json.dumps(counts, sort_keys=True))
    return counts


def verify_current_years(directory: Path, baseline: dict, *,
                         expected_years=YEARS) -> dict:
    """Verify each CURRENT parquet against authoritative manifest and Nov1 floor.

    Verify unique cross-year match IDs by streaming only the match_id column.
    The stable release downloader already verified the bundle SHA before use.
    """
    import pyarrow.parquet as pq

    current_manifest = json.loads((directory / "history_manifest.json").read_text())
    all_years = current_manifest.get("years")
    old_years = baseline.get("years")
    if not isinstance(all_years, dict) or not isinstance(old_years, dict):
        raise ValueError("Malformed current or prewrite CDB year manifest")
    years = {int(x) for x in all_years}
    if years != set(expected_years) or {int(x) for x in old_years} != set(expected_years):
        raise ValueError("Incomplete 78-year current/prewrite canonical inventory")
    seen = set()
    total = 0
    for year in sorted(years):
        meta = all_years[str(year)]
        previous = old_years[str(year)]
        if not isinstance(meta, dict) or not isinstance(previous, dict):
            raise ValueError("Malformed canonical yearly row record")
        filename = f"history-{year}.parquet"
        path = directory / filename
        if (meta.get("asset", filename) != filename or not path.is_file()
                or sha(path) != meta.get("sha256")
                or path.stat().st_size != int(meta.get("bytes", -1))):
            raise ValueError(f"Canonical {year} file/manifest SHA or length mismatch")
        parquet = pq.ParquetFile(path)
        count = parquet.metadata.num_rows
        if type(meta.get("rows")) is not int or type(previous.get("rows")) is not int:
            raise ValueError("Missing unambiguous canonical year row count")
        if count != meta["rows"] or count < previous["rows"]:
            raise ValueError(f"Canonical {year} row count changed below prewrite floor")
        for batch in parquet.iter_batches(batch_size=20000, columns=["match_id"]):
            for match_id in batch.column(0).to_pylist():
                if not match_id or match_id in seen:
                    raise ValueError("Duplicate/blank canonical match identity across years")
                seen.add(match_id)
        total += count
    if total != len(seen):
        raise ValueError("Canonical row count/unique identity discrepancy")
    return {"years_verified": len(years),
            "canonical_total_rows": total,
            "canonical_unique_match_ids": len(seen),
            "year_row_reductions_from_prewrite": 0,
            "duplicate_or_missing_match_ids": 0}


def verify_snapshot(root: Path) -> dict:
    """Independent final pinned-source and source-movement readback."""
    import pyarrow.parquet as pq
    current = root / "current"
    frozen = root / "frozen" / OLD_FILE
    if sha(frozen) != OLD_SHA:
        raise ValueError("Pinned original backup SHA no longer matches")
    inventory = assets(release(PREWRITE))
    names = ("history_manifest.json", "history-2026.parquet")
    prewrite_dir = root / "prewrite"
    prewrite = {n: download(PREWRITE, n, prewrite_dir, inventory[n])
                for n in names}
    if sha(prewrite["history_manifest.json"]) != PREWRITE_MANIFEST_SHA:
        raise ValueError("Pinned prewrite 1 Nov history manifest SHA mismatch")
    prewrite_manifest = json.loads(prewrite["history_manifest.json"].read_text())
    if prewrite_manifest["years"]["2026"]["sha256"] != sha(prewrite["history-2026.parquet"]):
        raise ValueError("Prewrite 2026 partition is inconsistent with frozen manifest")

    years = verify_current_years(current, prewrite_manifest)
    cols = ["match_id", "player1_id", "player2_id", "scheduled_at", "stats_json"]
    lineage = compare_lineage(
        pq.read_table(frozen, columns=cols),
        pq.read_table(prewrite["history-2026.parquet"], columns=cols),
        pq.read_table(current / "history-2026.parquet", columns=cols),
    )

    remote = release(TAG)
    if (stamp(remote) != stamp(json.loads((root / "current-release-stamp.json").read_text()))
            or sha(current / "history_manifest.json")
            != assets(remote)["history_manifest.json"]["digest"].removeprefix("sha256:")):
        raise RuntimeError("Canonical release changed during independent readback")
    return {
        "schema": 1,
        "state": "CURRENT_CDB_78_YEAR_IDENTITY_AND_EVIDENCE_VERIFIED",
        "baseline_source_run": 41310504634,
        "source_prewrite_tag": PREWRITE,
        "source_prewrite_manifest_sha256": PREWRITE_MANIFEST_SHA,
        "current_manifest_sha256": sha(current / "history_manifest.json"),
        "canonical_writes": 0,
        "provider_requests": 0,
        "model_changes": 0,
        **years,
        **lineage,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--restore-dir", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    if not args.restore_dir.is_dir():
        raise RuntimeError("Read-only stable restore snapshot not found")
    # A distinct remote release read marks the state at the beginning of the
    # full audit, and is compared to the release after all year+row checks.
    initial = release(TAG)
    args.restore_dir.joinpath("current-release-stamp.json").write_text(
        json.dumps(initial), encoding="utf-8")
    report = verify_snapshot(args.restore_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("CDB_2026_CURRENT_UNION_READBACK " + json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
