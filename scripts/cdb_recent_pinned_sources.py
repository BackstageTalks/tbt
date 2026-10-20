#!/usr/bin/env python3
"""Pinned recent match-level ATP/WTA source intake from owned Google Drive.

Six distinct original *match-level* files, not rolling/career aggregates.
No ID from these files is treated as a canonical CDB match/player ID.
All rows remain SOURCE ONLY until the canonical linker independently agrees.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cdb_wta_pinned_preflight import fetch_pinned, sha256

# tour, source year, Drive ID, SHA-256, pinned file size
SOURCES = (
    ("atp", 2023, "1N1fTNs5CmAbxoBy_1tDMuIQ1KCG3pBVS",
     "f4624ca8de126b4f069e65c6b390a2ae203c52dd250c0c159c058902e4da3751", 628328),
    ("atp", 2025, "1jrOw7Rza4H1JOaZUyCz29Kd9rZNNhTj2",
     "525ed919547aaafc04fd00a1d98d10ca20cc6266df530cdfd2ddd4a784616d96", 789757),
    ("atp", 2026, "109Be-erkHMKxCA8wRoU_wl63luE9Yrhw",
     "4e54ae8f2e443b4a4c491c38241b6f042454d6e4a65142f26a0095dc2fc72113", 676235),
    ("wta", 2024, "1zUO9mE9gjKruNP0I7psPyjMtSYfiuK-K",
     "d9bba2a0b3793f63c737ef62a809b82b56b3ad0ee94e1f95e78cecfac7615ed2", 542425),
    ("wta", 2025, "11Jp46Xo0CJopiYXmxnwaGNJma1C-DSRo",
     "e4eb002bc6d828b0bd21e04ed286e68722ddc8ccbbb27ea980bf62e938377f96", 565244),
    ("wta", 2026, "1E9OEwug0D7pHrdeS2mvOoVTskudmTHXF",
     "8fea203e3f4e731308b9ed2845059818d400aa6176c801279b24e846569e9d97", 255577),
)
MAX_SINGLE = 2 * 1024 * 1024


def fetch_sources(folder: Path, *, session=None) -> dict:
    if folder.exists() and any(folder.iterdir()):
        raise ValueError("Pinned recent-source directory must be empty")
    folder.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "state": "SOURCE_ONLY_NEEDS_CANONICAL_MATCH",
              "production_mutated": False, "api_requests": 0,
              "license_review_required": True,
              "sources": []}
    for tour, year, file_id, expected, bytes_expected in SOURCES:
        name = f"{tour}_matches_{year}.csv"
        path = folder / name
        amount = fetch_pinned(path, session=session, file_id=file_id,
                              expected_sha256=expected)
        if amount != bytes_expected or amount > MAX_SINGLE or sha256(path) != expected:
            raise ValueError(f"Pinned {tour} {year} source changed")
        report["sources"].append({
            "tour": tour, "year": year, "file": name,
            "source_sha256": expected, "source_bytes": amount,
        })
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    report = fetch_sources(args.out_dir)
    (args.out_dir / "source-manifest.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
