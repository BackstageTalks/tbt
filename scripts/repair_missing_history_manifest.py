"""Emergency recovery for a missing private history_manifest.json.

This maintenance command is intentionally explicit and conservative. It does not
rewrite any history parquet partition. Instead it downloads the current remote
history-YYYY.parquet assets, validates their structure/identity integrity,
reconstructs history_manifest.json from the actual partition contents, uploads
that manifest, rebuilds the release checksum bundle, and finally verifies a
normal fail-closed ReleaseStore download.

Use only when normal readers fail with:
    Required history manifest is missing: history_manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT
import release_store
from audit_history_data import audit_partition, _duplicate_details
from repair_history_bundle_integrity import repair_bundle_manifest
from tbt.data.history_snapshot import (
    MANIFEST_SCHEMA_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    write_manifest,
)

HISTORY_PARTITION = re.compile(r"history-(\d{4})\.parquet$")


def _download_asset(store: release_store.ReleaseStore, name: str, directory: Path) -> Path:
    release_store.gh(
        "release", "download", store.tag,
        "--repo", store.repository,
        "--pattern", name,
        "--dir", directory,
        "--clobber",
    )
    path = directory / name
    if not path.is_file() or path.stat().st_size <= 0:
        raise FileNotFoundError(f"Release asset download did not produce {name}")
    return path


def _partition_meta(path: Path, year: int) -> dict:
    frame = pd.read_parquet(path, engine="pyarrow")
    if frame.empty:
        raise ValueError(f"Refusing empty history partition: {path.name}")
    if "scheduled_at" not in frame.columns:
        raise ValueError(f"Invalid history partition {path.name}: scheduled_at missing")
    scheduled = pd.to_datetime(frame["scheduled_at"], utc=True, errors="coerce")
    if scheduled.isna().any():
        raise ValueError(f"Invalid scheduled_at value in {path.name}")
    actual_years = sorted({int(value) for value in scheduled.dt.year.unique()})
    if actual_years != [int(year)]:
        raise ValueError(
            f"Partition/year mismatch for {path.name}: contains years {actual_years}"
        )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "rows": int(len(frame)),
        "history_start": scheduled.min().isoformat(),
        "history_end": scheduled.max().isoformat(),
        "sha256": digest,
        "bytes": int(path.stat().st_size),
        "raw_provider_payload_included": False,
        "provider_context": (
            "identity + canonical category + compact venue/location + "
            "_tbt_environment only"
        ),
        "year": int(year),
        "asset": path.name,
        "coverage_status": "recovered_remote_partition",
    }


def repair_missing_manifest(store: release_store.ReleaseStore) -> dict:
    assets = store._asset_names()
    remote_partitions = sorted(
        name for name in assets if HISTORY_PARTITION.fullmatch(name)
    )
    if not remote_partitions:
        raise FileNotFoundError("No remote history-YYYY.parquet assets found")
    if "history_manifest.json" in assets:
        raise RuntimeError(
            "history_manifest.json already exists; use history-integrity-repair instead"
        )

    work_root = store.directory
    work_root.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "schema": 1,
        "status": "validating",
        "release_tag": store.tag,
        "remote_partitions": remote_partitions,
        "recovered_at": datetime.now(timezone.utc).isoformat(),
    }

    with tempfile.TemporaryDirectory(dir=work_root) as temporary_name:
        temporary = Path(temporary_name)
        summaries = []
        identities = []
        years: dict[str, dict] = {}

        for name in remote_partitions:
            match = HISTORY_PARTITION.fullmatch(name)
            assert match is not None
            year = int(match.group(1))
            path = _download_asset(store, name, temporary)
            summary, issues, partition_identities = audit_partition(path)
            if summary.get("fatal"):
                raise ValueError(f"{name}: {summary['fatal']}")
            if issues:
                raise ValueError(
                    f"History manifest recovery blocked: {name} has {len(issues)} invalid row(s)"
                )
            summaries.append(summary)
            identities.extend(partition_identities)
            years[str(year)] = _partition_meta(path, year)

        duplicate_match = _duplicate_details(identities, "match_id", "duplicate_match_id")
        duplicate_provider = _duplicate_details(
            identities, "provider_event_id", "duplicate_provider_event_id"
        )
        if duplicate_match or duplicate_provider:
            raise ValueError(
                "History manifest recovery blocked: duplicate identities found "
                f"(match_id={len(duplicate_match)}, provider_event_id={len(duplicate_provider)})"
            )

        manifest = {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "partition_schema_version": SNAPSHOT_SCHEMA_VERSION,
            "storage_policy": {"identity_provider": "firebase", "year_independent": True},
            "years": {key: years[key] for key in sorted(years, key=int)},
            "recovery": {
                "reason": "missing_remote_history_manifest",
                "method": "reconstructed_from_validated_remote_partitions",
                "recovered_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        manifest_path = write_manifest(work_root, manifest)

        # Publish the authoritative inventory first. release_store.gh has bounded
        # retries for transient GitHub 5xx/429 failures.
        store.upload([manifest_path])

        # Rebuild checksum coverage from the exact now-current remote assets.
        bundle = repair_bundle_manifest(store)

        report.update({
            "status": "repaired",
            "partition_count": len(remote_partitions),
            "total_rows": int(sum(item.get("rows", 0) for item in summaries)),
            "years": sorted(int(year) for year in years),
            "history_start": min(meta["history_start"] for meta in years.values()),
            "history_end": max(meta["history_end"] for meta in years.values()),
            "bundle_covered_count": len(bundle.get("files") or {}),
            "invalid_rows": 0,
            "duplicate_match_id_groups": 0,
            "duplicate_provider_event_id_groups": 0,
        })

    # Verify that an ordinary fail-closed reader accepts the repaired release.
    original_directory = store.directory
    try:
        with tempfile.TemporaryDirectory(dir=work_root) as verify_name:
            store.directory = Path(verify_name)
            store.download()
    finally:
        store.directory = original_directory
    report["verified_normal_download"] = True

    report_path = work_root / "history_manifest_repair_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    parser.add_argument("--release-tag", default="tbt-data-v1")
    parser.add_argument(
        "--work-dir",
        default=str(ROOT / ".cache" / "tbt" / "history-manifest-repair"),
    )
    args = parser.parse_args()
    store = release_store.ReleaseStore(
        args.data_repository, args.release_tag, Path(args.work_dir)
    )
    report = repair_missing_manifest(store)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
