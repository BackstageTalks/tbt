"""One-time/maintenance repair for legacy TBT history release checksum metadata.

This command never rewrites history parquet assets. It downloads the exact current
private release assets, verifies that history_manifest.json and the remote history
partition inventory agree, then replaces only _tbt_bundle_manifest.json with
SHA-256 coverage for the current release generation.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT
import release_store


HISTORY_PARTITION = re.compile(r"history-\d{4}\.parquet")


def _download_asset(store: release_store.ReleaseStore, name: str, directory: Path) -> Path:
    release_store.gh(
        "release",
        "download",
        store.tag,
        "--repo",
        store.repository,
        "--pattern",
        name,
        "--dir",
        directory,
        "--clobber",
    )
    path = directory / name
    if not path.is_file():
        raise FileNotFoundError(f"Release asset download did not produce {name}")
    return path


def repair_bundle_manifest(store: release_store.ReleaseStore) -> dict:
    """Rebuild checksum metadata from the exact current private release assets.

    Normal readers stay fail-closed. This explicit maintenance operation is the
    only path that can establish checksum coverage for legacy assets that predate
    the bundle manifest.
    """
    assets = store._asset_names()
    if "history_manifest.json" not in assets:
        raise FileNotFoundError("Cannot repair integrity metadata without history_manifest.json")

    with tempfile.TemporaryDirectory(dir=store.directory) as temporary_name:
        temporary = Path(temporary_name)
        history_manifest_path = _download_asset(store, "history_manifest.json", temporary)
        try:
            history_manifest = json.loads(history_manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid history manifest") from exc

        years = history_manifest.get("years") if isinstance(history_manifest, dict) else None
        if not isinstance(years, dict):
            raise ValueError("Invalid history manifest: missing years map")

        expected_history = set()
        for year, metadata in years.items():
            if not isinstance(metadata, dict):
                raise ValueError(f"Invalid history manifest entry for year {year}")
            asset = str(metadata.get("asset") or f"history-{int(year):04d}.parquet")
            if not HISTORY_PARTITION.fullmatch(asset):
                raise ValueError(f"Invalid history partition asset in manifest: {asset}")
            expected_history.add(asset)

        remote_history = {name for name in assets if HISTORY_PARTITION.fullmatch(name)}
        missing = sorted(expected_history - remote_history)
        extra = sorted(remote_history - expected_history)
        if missing:
            raise FileNotFoundError(
                "History manifest references missing release assets: " + ", ".join(missing)
            )
        if extra:
            raise RuntimeError(
                "Remote history assets are not declared by history_manifest.json: "
                + ", ".join(extra)
            )

        # Rebuild coverage for every current release asset, except the checksum
        # manifest itself. This preserves integrity metadata for operational
        # assets without modifying any of those assets.
        covered_assets = sorted(name for name in assets if name != store.BUNDLE_MANIFEST)
        files = {}
        for name in covered_assets:
            path = history_manifest_path if name == "history_manifest.json" else _download_asset(store, name, temporary)
            files[name] = {
                "sha256": store._sha256(path),
                "bytes": int(path.stat().st_size),
            }

        manifest = {
            "schema": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
        }
        manifest_path = store.directory / store.BUNDLE_MANIFEST
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_manifest = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        temporary_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary_manifest.replace(manifest_path)
        store.upload([manifest_path])
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"),
    )
    parser.add_argument("--release-tag", default="tbt-data-v1")
    parser.add_argument(
        "--work-dir",
        default=str(ROOT / ".cache" / "tbt" / "history-integrity-repair"),
    )
    args = parser.parse_args()

    store = release_store.ReleaseStore(args.data_repository, args.release_tag, Path(args.work_dir))
    manifest = repair_bundle_manifest(store)
    print(json.dumps({
        "status": "repaired",
        "release_tag": args.release_tag,
        "covered_assets": sorted(manifest["files"]),
        "covered_count": len(manifest["files"]),
    }, indent=2))


if __name__ == "__main__":
    main()
