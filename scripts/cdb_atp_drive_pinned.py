#!/usr/bin/env python3
"""SHA-pinned small ATP Drive workbook intake, SOURCE ONLY, never CDB writes.

2017 workbook is a PARTIAL source (~388 match rows). The source's tournament
date is NOT assumed to be the exact match date. Raw IDs are provenance, not
canonical match IDs. No data license is inferred from possession in Drive.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cdb_wta_pinned_preflight import fetch_pinned, sha256

PINNED = (
    (2016, "1ELx4RYQP5Q3IyRFU8hzPNkgHR23UlbzL",
     "31e1d3d3a54435b272e13983ea78798d4e17608d65118b43a5a81d8cac77f730", 737884),
    (2017, "1XMYd8u1uErPOhnxBBhfzfrX48JWLscKd",
     "c815fb03515f9c930cdcee7dd1230fa74da16039e6ad9d6d73667a5ed8ef52cf", 106785),
)
MAX_FILE_BYTES = 2 * 1024 * 1024


def fetch_sources(output: Path, *, session=None) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("ATP intake output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": 1, "state": "SOURCE_ONLY", "production_mutated": False,
                "api_requests": 0, "license_review_required": True,
                "sources": []}
    for year, file_id, expected_sha, size in PINNED:
        path = output / f"atp_matches_{year}.xlsx"
        actual = fetch_pinned(path, session=session,
                              file_id=file_id, expected_sha256=expected_sha)
        if actual != size or actual > MAX_FILE_BYTES or sha256(path) != expected_sha:
            raise ValueError(f"ATP {year} original file changed")
        manifest["sources"].append({"year": year, "source_sha256": expected_sha,
                                    "source_bytes": actual, "file": path.name})
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    report = fetch_sources(args.out_dir)
    (args.out_dir / "source-manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
