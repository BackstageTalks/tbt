"""Download a coherent canonical release while another repository may publish.

A manifest/partition race is retryable only if the remote manifest changed.
A stable checksum failure is corruption and must fail closed. This script
never writes remote state and makes no provider API calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from release_store import ReleaseStore

MANIFEST = "_tbt_bundle_manifest.json"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def download_stable(repository: str, tag: str, destination: Path, attempts: int = 4) -> dict:
    if attempts < 1 or attempts > 6:
        raise ValueError("Refuse unbounded or zero retry count")
    for attempt in range(1, attempts + 1):
        scratch = destination.parent / (destination.name + ".snapshot-part")
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir(parents=True)
        store = ReleaseStore(repository, tag, scratch)
        before = None
        try:
            # Read manifest independently both before and after the bundle.
            if MANIFEST not in store._asset_names():
                raise FileNotFoundError("Canonical bundle manifest missing")
            store._download_asset(MANIFEST)
            before = _sha(scratch / MANIFEST)
            store.download(require_bundle_manifest=True)
            store._download_asset(MANIFEST)
            after = _sha(scratch / MANIFEST)
            if before != after:
                raise RuntimeError("Canonical manifest changed mid-download")
            # download verified every covered file against its first manifest;
            # second manifest has the identical SHA so the snapshot is stable.
            if destination.exists():
                shutil.rmtree(destination)
            scratch.replace(destination)
            return {"schema": 1, "status": "verified",
                    "manifest_sha256": after, "attempt": attempt,
                    "provider_api_requests": 0}
        except (RuntimeError, FileNotFoundError) as exc:
            # Retry only if *independent remote* manifest moved: an unchanged
            # checksum mismatch must never be disguised as publication churn.
            moved = False
            try:
                store._download_asset(MANIFEST)
                moved = before is not None and before != _sha(scratch / MANIFEST)
            except Exception:
                pass
            if not moved or attempt == attempts:
                raise RuntimeError(
                    f"Canonical snapshot unavailable; abort without write "
                    f"(attempt {attempt}/{attempts}, manifest_moved={moved}): {exc}"
                ) from exc
    raise AssertionError("Unreachable")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repository", required=True)
    p.add_argument("--tag", default="tbt-data-v1")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    args = p.parse_args()
    report = download_stable(args.repository, args.tag, args.out)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
