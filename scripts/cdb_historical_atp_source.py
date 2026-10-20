#!/usr/bin/env python3
"""Pinned offline source-only intake: ATP matchlevel 1991-2018; use 2016-2018.

The source is original complete match-level data, not lifetime/rolling
aggregates. Its winner/loser IDs are SOURCE SLUGS, NOT canonical CDB IDs.
Never import directly from source without strict independent canonical linking.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
import json
from pathlib import Path

from cdb_wta_pinned_preflight import fetch_pinned, sha256

FILE_ID = "1q0sKRNX1Fv7SqXQdTt8JKR0NZ52lWe_f"
SOURCE_SHA256 = "290430ff7d1d4d6901f2545c5c862b424af042fc95064d5808fb051f3ee31284"
SOURCE_BYTES = 28_884_652
NEEDED = frozenset((
    "tourney_date", "tourney_name", "surface", "round", "winner_name",
    "loser_name", "winner_id", "loser_id", "match_num", "tourney_id",
    "w_svpt", "l_svpt", "w_1stIn", "l_1stIn", "w_1stWon", "l_1stWon",
    "w_2ndWon", "l_2ndWon",
))
MAX_ROWS = 200_000


def check_source(path: Path, expected_sha256: str = SOURCE_SHA256) -> dict:
    if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Missing/unbounded ATP matchlevel source")
    if sha256(path) != expected_sha256:
        raise ValueError("Original ATP matchlevel SHA-256 mismatch")
    rows = Counter()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if not NEEDED.issubset(fields) or len(fields) != len(set(fields)):
            raise ValueError("Unexpected ATP matchlevel schema")
        for number, row in enumerate(reader, 1):
            if number > MAX_ROWS or None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed ATP matchlevel source row")
            rows["raw_rows"] += 1
            year = str(row["tourney_date"])[:4]
            if year not in ("2016", "2017", "2018"):
                continue
            rows["2016_2018_raw_rows"] += 1
            if not row["winner_id"] or not row["loser_id"]:
                rows["missing_source_player_slugs"] += 1
            if row["w_svpt"] and row["l_svpt"]:
                rows["2016_2018_with_serve_stats"] += 1
            rows[f"year_{year}"] += 1
    if sha256(path) != expected_sha256:
        raise ValueError("Original source bytes changed during review")
    return {
        "schema": 1, "state": "ORIGINAL_SOURCE_ONLY_NO_CDB_WRITE",
        "production_mutated": False, "api_requests": 0,
        "source_sha256": expected_sha256, "source_bytes": path.stat().st_size,
        "counts": dict(sorted(rows.items())),
        "license_review_required": True,
        "canonical_matches_confirmed": 0,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise ValueError("Pinned output directory must be empty")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    src = args.output_dir / "all_matches_matchlevel_1991_2018.csv"
    amount = fetch_pinned(src, file_id=FILE_ID, expected_sha256=SOURCE_SHA256)
    if amount != SOURCE_BYTES:
        raise ValueError("Original source size changed")
    report = check_source(src)
    (args.output_dir / "source-check.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
