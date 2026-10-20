#!/usr/bin/env python3
"""Build a read-only, manifest-consistent 2016-2020 view of verified CDB history.

The canonical private release is never modified. The view is a disposable copy:
history_snapshot.load_partitions intentionally rejects a missing partition listed
in the full release manifest, so a separately verified reduced manifest is needed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

YEARS = tuple(range(2016, 2021))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def verified_window(source: Path, release_metadata: Path, output: Path,
                    years: tuple[int, ...] = YEARS) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output view must be empty")
    if not years or any(y < 2016 or y > 2026 for y in years) or len(years) != len(set(years)):
        raise ValueError("Invalid canonical partition selection")
    if source.resolve() == output.resolve():
        raise ValueError("Never overwrite private source snapshot")

    release = json.loads(release_metadata.read_text(encoding="utf-8"))
    if release.get("tag_name") != "tbt-data-v1":
        raise ValueError("Unexpected private release tag")
    assets = {row["name"]: row for row in release["assets"]}
    history_path = source / "history_manifest.json"
    bundle_path = source / "_tbt_bundle_manifest.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    if not isinstance(history.get("years"), dict) or not isinstance(bundle.get("files"), dict):
        raise ValueError("Malformed canonical release manifests")

    for name in ("history_manifest.json", "_tbt_bundle_manifest.json"):
        file_sha = sha256(source / name)
        if assets.get(name, {}).get("digest") != "sha256:" + file_sha:
            raise ValueError("Private release manifest digest mismatch: " + name)
        if name in bundle["files"] and bundle["files"][name]["sha256"] != file_sha:
            raise ValueError("Bundle manifest digest mismatch: " + name)

    entries = {}
    report = {"schema": 1, "state": "VERIFIED_PRIVATE_CDB_LOCAL_VIEW",
              "production_mutated": False, "api_requests": 0,
              "release": "tbt-data-v1",
              "original_manifest_sha256": sha256(history_path),
              "original_bundle_sha256": sha256(bundle_path),
              "partitions": {}}
    for year in sorted(years):
        name = f"history-{year}.parquet"
        entry = history["years"].get(str(year))
        if not isinstance(entry, dict) or entry.get("asset", name) != name:
            raise ValueError("Missing/invalid canonical year: " + name)
        digest = sha256(source / name)
        if (entry.get("sha256") != digest
                or bundle["files"].get(name, {}).get("sha256") != digest
                or assets.get(name, {}).get("digest") != "sha256:" + digest):
            raise ValueError("Canonical year checksum mismatch: " + name)
        entries[str(year)] = dict(entry)
        report["partitions"][str(year)] = {
            "sha256": digest, "bytes": (source / name).stat().st_size,
        }

    output.mkdir(parents=True, exist_ok=True)
    for year in sorted(years):
        name = f"history-{year}.parquet"
        shutil.copy2(source / name, output / name)
        if sha256(output / name) != report["partitions"][str(year)]["sha256"]:
            raise ValueError("Local canonical copy checksum mismatch: " + name)
    reduced = dict(history)
    reduced["years"] = entries
    (output / "history_manifest.json").write_text(
        json.dumps(reduced, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--release-metadata", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = verified_window(args.source, args.release_metadata, args.output)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
