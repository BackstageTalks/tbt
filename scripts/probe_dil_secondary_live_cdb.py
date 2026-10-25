#!/usr/bin/env python3
"""Read-only, bounded SHA-pinned full release preflight for CDB -> secondary DIL.

Must run on an authorized trusted private-token runner. The full 78-part source
is held in scratch only; NEVER upload private partitions to a public artifact.
No CDB write, no DIL publication, no model fitting and no match-level logs.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from build_current_cdb_compare import release_assets, validate_sources

REPO = "BackstageTalks/tbt-data"
TAG = "tbt-data-v1"
PARTITIONS = 78


class ReleaseDriftError(RuntimeError):
    """The release changed while we obtained a local private snapshot."""


def gh(*arguments):
    try:
        result = subprocess.run(
            ["gh", *arguments], check=False, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("BLOCKED_GH_NOT_INSTALLED") from exc
    if result.returncode != 0:
        raise RuntimeError("BLOCKED_PRIVATE_GITHUB_READ_FAILED")
    return result.stdout


def read_release():
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("BLOCKED_PRIVATE_GITHUB_READ_TOKEN_MISSING")
    private = gh("api", f"repos/{REPO}", "--jq", ".private").strip()
    if private != "true":
        raise RuntimeError("BLOCKED_CDB_SOURCE_PRIVACY_UNVERIFIED")
    return json.loads(gh("api", f"repos/{REPO}/releases/tags/{TAG}"))


def fetch_release_assets(directory: Path):
    directory.mkdir(parents=True, exist_ok=False)
    gh("release", "download", TAG, "-R", REPO,
       "-p", "history-*.parquet", "-p", "history_manifest.json",
       "-p", "_tbt_bundle_manifest.json", "-D", str(directory))


def pinned_metadata(release):
    return release_assets(release)


def verify_once(folder: Path, *, read_metadata=read_release,
                downloader=fetch_release_assets, expected_parts=PARTITIONS):
    initial = read_metadata()
    if initial.get("tag_name") != TAG:
        raise ValueError("CDB release tag mismatch")
    initial_receipt = pinned_metadata(initial)
    if len([k for k in initial_receipt if k.startswith("history-") and k.endswith(".parquet")]) != expected_parts:
        raise ValueError("CDB release partition inventory incomplete")
    try:
        downloader(folder)
    except Exception as exc:
        # A failed download can reflect publication churn; retry only when
        # the independently re-read release metadata demonstrably changed.
        if pinned_metadata(read_metadata()) != initial_receipt:
            raise ReleaseDriftError("CDB release changed during download") from exc
        raise RuntimeError("CDB binary download failed against unchanged release") from exc
    middle = read_metadata()
    if pinned_metadata(middle) != initial_receipt:
        raise ReleaseDriftError("CDB release changed after download")
    proof = validate_sources(folder, initial, middle, expected_parts=expected_parts)
    final = read_metadata()
    if pinned_metadata(final) != initial_receipt:
        raise ReleaseDriftError("CDB release changed during source checksum proof")
    # The complete downloaded bytes, manifest and bundle must agree with the
    # same immutable release metadata. No CDB rows are interpreted or exported.
    return {
        "schema": "DIL_SECONDARY_CDB_FULL_SOURCE_PROBE_V1",
        "status": "VERIFIED_78_PART_SOURCE_SNAPSHOT" if expected_parts == PARTITIONS else "VERIFIED_TEST_FIXTURE",
        "tag": TAG,
        "partition_count": proof["year_count"],
        "sha256_manifest": proof["release_manifest_sha256"],
        "sha256_bundle": proof["bundle_manifest_sha256"],
        "source_bytes": proof["release_part_bytes"],
        "release_metadata_before_equals_after": True,
        "source_binary_sha256s_verified": True,
        "cdb_mutated": False,
        "dil_mutated": False,
        "cdb_dil_parity_achieved": False,
        "production_change_authorized": False,
    }


def probe(directory: Path, *, read_metadata=read_release,
          downloader=fetch_release_assets, attempts=3, expected_parts=PARTITIONS):
    root = Path(directory).resolve()
    if not 1 <= attempts <= 4:
        raise ValueError("Only 1-4 bounded attempts are permitted")
    if root.exists():
        raise FileExistsError("Refusing to overwrite existing private probe directory")
    root.mkdir(parents=True)
    try:
        for attempt in range(1, attempts + 1):
            current = root / f"attempt-{attempt}"
            try:
                result = verify_once(current, read_metadata=read_metadata,
                                     downloader=downloader, expected_parts=expected_parts)
                result["attempt"] = attempt
                return result
            except ReleaseDriftError:
                if attempt == attempts:
                    raise RuntimeError("BLOCKED_SOURCE_RACE_AFTER_BOUNDED_ATTEMPTS")
            finally:
                shutil.rmtree(current, ignore_errors=False) if current.exists() else None
    finally:
        # Strict private-ephemeral mode: release bytes and any residual metadata
        # never survive the probe, even when a source is corrupt or moves.
        shutil.rmtree(root)
    raise AssertionError("unreachable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = probe(args.scratch)
    except Exception as exc:
        # Redact paths, asset names and exception chains on a public runner.
        name = type(exc).__name__
        code = (str(exc) if str(exc).startswith("BLOCKED_") else
                "SOURCE_DRIFT" if isinstance(exc, ReleaseDriftError) else "PRIVATE_SOURCE_VALIDATION_FAILED")
        print("DIL_SECONDARY_CDB_SOURCE_PRECHECK_BLOCKED", name, code, file=sys.stderr)
        return 2
    # Non-sensitive aggregate receipts only; no player IDs, names or results.
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())