#!/usr/bin/env python3
"""Read every ACTIVE private Release asset byte and verify pinned SHA256.

No tennis-provider requests, no CDB writes, no training; only GitHub Releases.
The asset membership snapshot is immutable per run; replacement during the run
is reported as drift, never treated as valid new data.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile


def file_hash(path):
    h = sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_release(repo, tag, output):
    subprocess.run(
        ["gh", "release", "download", tag, "--repo", repo, "--dir", str(output)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        timeout=1200,
    )


def audit(releases, repo, workspace, *, downloader=download_release):
    workspace.mkdir(parents=True, exist_ok=True)
    issues = []
    entries = []
    counts = Counter()
    start = {
        "snapshot_releases": len(releases),
        "snapshot_assets": sum(len(x.get("assets", [])) for x in releases),
        "snapshot_expected_bytes": sum(int(a.get("size") or 0)
            for x in releases for a in x.get("assets", [])),
    }
    seen_ids = set()
    for rel in releases:
        tag = rel["tag_name"]
        assets = rel.get("assets", [])
        if not assets:
            counts["zero_asset_release_tags"] += 1
            continue
        expected = {}
        for a in assets:
            if a["id"] in seen_ids or a["name"] in expected:
                raise ValueError("Duplicate active asset ID or name in release snapshot")
            seen_ids.add(a["id"])
            expected[a["name"]] = a
        with tempfile.TemporaryDirectory(prefix="blinq-rel-bytes-", dir=str(workspace)) as directory:
            dest = Path(directory)
            try:
                downloader(repo, tag, dest)
                counts["release_downloads_completed"] += 1
            except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired) as exc:
                counts["release_download_failures"] += 1
                issues.append({"tag": tag, "issue": "RELEASE_DOWNLOAD_FAILED",
                               "type": type(exc).__name__})
                for a in assets:
                    entries.append({"tag": tag, "id": a["id"],
                                    "name": a["name"], "verified": False,
                                    "reason": "RELEASE_DOWNLOAD_FAILED"})
                continue
            received = {p.name: p for p in dest.iterdir() if p.is_file()}
            unexpected = set(received) - set(expected)
            for name in unexpected:
                issues.append({"tag": tag, "issue": "UNEXPECTED_ASSET_FILENAME",
                               "name": name})
            for name, a in expected.items():
                counts["asset_metadata_rows_checked"] += 1
                item = {"tag": tag, "id": a["id"], "name": name,
                        "expected_bytes": a["size"], "expected_digest": a.get("digest")}
                path = received.get(name)
                if path is None:
                    item.update(verified=False, reason="MISSING_ASSET")
                    counts["missing_assets"] += 1
                else:
                    actual_bytes = path.stat().st_size
                    actual_hash = file_hash(path)
                    counts["asset_bytes_read"] += actual_bytes
                    counts["asset_files_sha256_computed"] += 1
                    item.update(actual_bytes=actual_bytes,
                                actual_sha256=actual_hash)
                    claimed = a.get("digest")
                    if actual_bytes != a["size"]:
                        item.update(verified=False, reason="SIZE_MISMATCH")
                        counts["size_mismatches"] += 1
                    elif claimed != "sha256:" + actual_hash:
                        item.update(verified=False, reason="SHA256_MISMATCH")
                        counts["digest_mismatches"] += 1
                    else:
                        item.update(verified=True, reason="CHECKSUM_MATCHES_RELEASE_METADATA")
                        counts["assets_byte_verified"] += 1
                entries.append(item)
        print("RELEASE_BYTE_AUDIT_PROGRESS",
              counts["release_downloads_completed"] + counts["release_download_failures"],
              len(releases), "VERIFIED_ASSETS", counts["assets_byte_verified"], flush=True)

    total_count = len(entries)
    if total_count != start["snapshot_assets"]:
        issues.append({"issue": "REPORT_CARDINALITY_MISMATCH",
                       "expected": start["snapshot_assets"], "actual": total_count})
    failed = [x for x in entries if not x.get("verified")]
    result = {
        "schema": 1,
        "scope": "Every active GitHub Release asset in one pinned per-run private metadata snapshot",
        "repo": repo,
        "status": "ALL_ACTIVE_RELEASE_ASSET_BYTES_SHA256_VERIFIED"
                  if not failed and not issues else "RELEASE_ASSET_BYTE_AUDIT_INCOMPLETE_OR_CONFLICTED",
        "snapshot": start,
        "counts": dict(sorted(counts.items())),
        "assets_not_byte_verified": len(failed),
        "issues": issues,
        "source_rows_or_player_details_not_exported": True,
        "canonical_cdb_writes": 0,
        "model_train_or_promotion": False,
        "provider_tennis_api_requests": 0,
        "method": "Independent downloaded-file SHA256, metadata asset ID+size+digest and exact release asset membership",
        "limit": "Byte integrity does not prove provider content completeness, license, temporal safety, match identity, or a positive canonical CDB delta",
    }
    return result, entries


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--summary", type=Path, required=True)
    p.add_argument("--private-index", type=Path, required=True)
    a = p.parse_args()
    snapshot = json.loads(a.snapshot.read_text())
    report, records = audit(snapshot, a.repo, a.work)
    a.summary.parent.mkdir(parents=True, exist_ok=True)
    a.private_index.parent.mkdir(parents=True, exist_ok=True)
    a.summary.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    with gzip.open(a.private_index, "wt", encoding="utf-8") as f:
        for row in records:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print("RELEASE_BYTE_AUDIT_COMPLETE",
          json.dumps({"status":report["status"], "snapshot":report["snapshot"],
                      "counts":report["counts"],"assets_not_byte_verified":report["assets_not_byte_verified"]},
                      sort_keys=True))


if __name__ == "__main__":
    main()
