"""Restore pinned, persisted 24h forecast inputs for every training rebuild.

No collection/provider API; reject absent manifest, changed bytes or malformed input.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import shutil
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from rank_feature_inputs import _manifest_asset, _sha256, _source_manifest
from release_store import ReleaseStore

ASSET = "openmeteo-pre-match-24h-2024-2026.csv.gz"
RELEASE = "tbt-research-sources-v1"
REQUIRED = {
    "match_id", "forecast_lead_hours", "forecast_reference", "source",
    "temperature_c", "relative_humidity_pct", "surface_pressure_hpa",
    "wind_speed_kmh", "wind_gusts_kmh",
}


def restore_weather(repository: str, source_dir: Path, out: Path) -> dict:
    if not repository:
        raise ValueError("Private destination repository is required")
    source_dir.mkdir(parents=True, exist_ok=True)
    release = ReleaseStore(repository, RELEASE, source_dir)
    release.download(extra_names=(ASSET,), required_names=(ASSET,))
    compressed = source_dir / ASSET
    manifest_entry = _manifest_asset(_source_manifest(repository), ASSET)
    sha = _sha256(compressed)
    if sha != manifest_entry["sha256"]:
        raise ValueError("Pre-match forecast SHA-256 mismatch")
    if compressed.stat().st_size != int(manifest_entry["bytes"]):
        raise ValueError("Pre-match forecast byte count mismatch")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    try:
        with gzip.open(compressed, "rt", encoding="utf-8", newline="") as read, (
            tmp.open("w", encoding="utf-8", newline="")
        ) as write:
            header = next(csv.reader(read))
            if not REQUIRED.issubset(header) or len(set(header)) != len(header):
                raise ValueError("Invalid verified 24h forecast CSV schema")
            read.seek(0)
            shutil.copyfileobj(read, write)
        with out.with_suffix(out.suffix + ".part").open(
            encoding="utf-8", newline=""
        ) as fh:
            reader = csv.DictReader(fh)
            count = 0
            for row in reader:
                if row["forecast_lead_hours"] not in {"24", "24.0"}:
                    raise ValueError("Forecast lead is not exactly 24h")
                if row["forecast_reference"] != "previous_day1":
                    raise ValueError("Forecast is not from the previous day")
                count += 1
            if count < 1000:
                raise ValueError("Suspiciously small historical forecast input")
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return {
        "schema": 1, "status": "verified", "source_release": RELEASE,
        "asset": ASSET, "sha256": sha, "rows": count,
        "fixed_forecast_lead_hours": 24, "provider_requests": 0,
        "output_csv_sha256": _sha256(out),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repository", required=True)
    p.add_argument("--source-dir", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    args = p.parse_args()
    result = restore_weather(args.repository, args.source_dir, args.out)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
