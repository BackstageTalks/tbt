"""Private read-only forensics for 2026 ID drift after 1 Nov restoration.

Only aggregate evidence is retained; raw match IDs and cells never leave
the ephemeral CI runner. Reuses existing ReleaseStore-backed stable download
and SHA-pinned backup/identity checks. No canonical writer or paid provider.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from download_stable_cdb import download_stable
from restore_cdb_2026_lossless import (
    BACKUP, OLD_FILE, OLD_MANIFEST, OLD_SHA, OLD_MANIFEST_SHA,
    REPO, TAG, assets, download, index, merge_preserving_live,
    release, sha, stamp, verify_cross_year,
)
from verify_cdb_2026_postrestore import (
    PREWRITE, PREWRITE_MANIFEST_SHA, verify_current_years,
)


def compare_origins(old, before, live):
    older = index(old, "pinned_backup")
    prewrite = index(before, "prewrite")
    current = index(live, "current")
    shared = set(older) & set(prewrite)
    old_only = set(older) - set(prewrite)
    prewrite_only = set(prewrite) - set(older)
    if not (len(older) == 98994 and len(prewrite) == 2927
            and len(shared) == 1258 and len(old_only) == 97736
            and len(prewrite_only) == 1669):
        raise ValueError("Original two authoritative 1 Nov CDB cohorts changed")
    prewrite_missing = set(prewrite) - set(current)
    backup_missing = set(older) - set(current)
    prewrite_identity_conflicts = 0
    for mid in set(prewrite) & set(current):
        i, j = prewrite[mid], current[mid]
        if any(before[key][i].as_py() != live[key][j].as_py()
               for key in ("player1_id", "player2_id", "scheduled_at")):
            prewrite_identity_conflicts += 1
    return {
        "backup_ids_missing_now": len(backup_missing),
        "prewrite_ids_missing_now": len(prewrite_missing),
        "original_backup_only_id_count": len(old_only),
        "original_prewrite_only_id_count": len(prewrite_only),
        "original_overlap": len(shared),
        "prewrite_identity_conflicts_now": prewrite_identity_conflicts,
        "prewrite_only_ids_preserved_now": len(prewrite_only - prewrite_missing),
        "baseline_2026_original_row_count": len(older),
        "baseline_2026_prewrite_row_count": len(prewrite),
        "current_2026_rows": len(current),
    }


def _store_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("CDB_2026_DRIFT_FORENSICS " + json.dumps(report, sort_keys=True), flush=True)


def main() -> None:
    import pyarrow.parquet as pq

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if os.getenv("GITHUB_ACTIONS") != "true" or not os.getenv("GH_TOKEN"):
        raise RuntimeError("Private GitHub Actions read-only credentials required")
    root = args.out
    root.mkdir(parents=True, exist_ok=False)

    original_release = assets(release(BACKUP))
    if (original_release[OLD_FILE]["digest"] != "sha256:" + OLD_SHA or
            original_release[OLD_MANIFEST]["digest"] != "sha256:" + OLD_MANIFEST_SHA):
        raise RuntimeError("Original Oct 27 backup changed")
    frozen = download(BACKUP, OLD_FILE, root / "frozen", original_release[OLD_FILE])
    frozen_manifest = download(
        BACKUP, OLD_MANIFEST, root / "frozen", original_release[OLD_MANIFEST])
    if json.loads(frozen_manifest.read_text())["years"]["2026"]["sha256"] != OLD_SHA:
        raise RuntimeError("Original backup manifest inconsistent")

    beginning = release(TAG)
    snapshot = download_stable(REPO, TAG, root / "current")
    if snapshot["status"] != "verified" or stamp(beginning) != stamp(release(TAG)):
        raise RuntimeError("Current canonical release moved during stable download")

    older_assets = assets(release(PREWRITE))
    prewrite_manifest_path = download(
        PREWRITE, "history_manifest.json", root / "prewrite",
        older_assets["history_manifest.json"])
    prewrite_file = download(
        PREWRITE, "history-2026.parquet", root / "prewrite",
        older_assets["history-2026.parquet"])
    if sha(prewrite_manifest_path) != PREWRITE_MANIFEST_SHA:
        raise RuntimeError("Pinned 1 Nov prewrite manifest changed")
    previous = json.loads(prewrite_manifest_path.read_text())
    if previous["years"]["2026"]["sha256"] != sha(prewrite_file):
        raise RuntimeError("Pinned 1 Nov prewrite parquet changed")

    current = root / "current"
    cols = ["match_id", "player1_id", "player2_id", "scheduled_at", "stats_json"]
    old_table = pq.read_table(frozen, columns=cols)
    prewrite_table = pq.read_table(prewrite_file, columns=cols)
    current_table = pq.read_table(current / "history-2026.parquet", columns=cols)
    merged, counts, union = merge_preserving_live(old_table, current_table)
    origins = compare_origins(old_table, prewrite_table, current_table)
    report = {
        "schema": 1, "phase": "read_only_current_snapshot_forensics",
        "state": "UNVERIFIED_UNTIL_COMPLETE",
        "original_persisted_restore_run": 41310504634,
        "source_prewrite_tag": PREWRITE,
        "current_manifest_sha256": snapshot["manifest_sha256"],
        "model_changes": 0, "provider_requests": 0, "cdb_writes": 0,
        "recovery_candidate_not_imported": True,
        "merged_candidate_rows_only_in_memory": merged.num_rows,
        **counts, **origins,
    }
    output = root / "drift-report.json"
    _store_report(output, report)
    # The old/current identity union is checked for collisions even when the
    # original release is incomplete. Nothing is uploaded or published.
    report["other_year_unique_ids"] = verify_cross_year(current, union)
    report.update(verify_current_years(current, previous))
    # Remote CAS-style independent inventory observation after full scan.
    latest = release(TAG)
    if stamp(beginning) != stamp(latest):
        raise RuntimeError("Canonical CDB changed during identity forensics")
    restored_missing = counts["old_only_restored"]
    if restored_missing != origins["backup_ids_missing_now"]:
        raise RuntimeError("Independent identity gap computations disagree")
    report["state"] = (
        "CURRENT_IDENTITY_UNION_VERIFIED"
        if not restored_missing and not origins["prewrite_ids_missing_now"]
        and not origins["prewrite_identity_conflicts_now"]
        else "CURRENT_IDENTITY_REVIEW_REQUIRED"
    )
    _store_report(output, report)
    if report["state"] != "CURRENT_IDENTITY_UNION_VERIFIED":
        raise RuntimeError("Current canonical identity drift detected; review only, no write")


if __name__ == "__main__":
    main()
