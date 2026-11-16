#!/usr/bin/env python3
"""Source-only QA for independently SHA-pinned TennisMyLife mirror CSVs.

Never changes canonical CDB. Carries source-local player/event identifiers
only as provenance; downstream ID/event corroboration is mandatory for writes.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from prepare_tml_atp_cdb import (
    STATS, ID, blob_sha1, complete_winner_score, valid_tourney_season_start,
)

REQUIRED = set(STATS) | {
    "tourney_id", "tourney_name", "tourney_date", "match_num",
    "winner_id", "loser_id", "winner_name", "loser_name", "surface",
    "round", "best_of", "score",
}


def _numbers(row: dict[str, str]) -> dict[str, int] | None:
    values: dict[str, int] = {}
    for field in STATS:
        raw = row[field].strip()
        if not raw:
            continue
        if not raw.isascii() or not raw.isdecimal():
            return None
        values[field] = int(raw)
    for prefix in ("w", "l"):
        def n(field: str) -> int | None:
            return values.get(f"{prefix}_{field}")
        for a, b in (
            ("1stIn", "svpt"), ("1stWon", "1stIn"),
            ("bpSaved", "bpFaced"),
        ):
            if n(a) is not None and n(b) is not None and n(a) > n(b):
                return None
        if (n("svpt") is not None and n("1stIn") is not None
                and n("2ndWon") is not None
                and n("2ndWon") > n("svpt") - n("1stIn")):
            return None
        if (n("ace") is not None and n("1stWon") is not None
                and n("2ndWon") is not None
                and n("ace") > n("1stWon") + n("2ndWon")):
            return None
        if (n("df") is not None and n("svpt") is not None
                and n("1stIn") is not None
                and n("df") > n("svpt") - n("1stIn")):
            return None
    return values


def prepare(root: Path, manifest_path: Path, output: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("source_files")
    if (manifest.get("schema") != 1 or
            manifest.get("mode") != "SOURCE_ONLY_READONLY_CURRENT_CDB_STAGING" or
            not isinstance(entries, list) or not entries):
        raise ValueError("Missing or invalid source-only pinned inventory")
    seen_paths: set[str] = set()
    counts = Counter()
    report_files: list[dict] = []
    output.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        path = entry.get("path")
        year = entry.get("year")
        tour = entry.get("tour")
        expected = entry.get("git_blob_sha")
        size = entry.get("size")
        if (not isinstance(path, str) or ".." in Path(path).parts or
                path.startswith("/") or path in seen_paths or
                not isinstance(year, int) or not 2016 <= year <= 2026 or
                tour not in ("wta", "atp_challenger", "atp_tour") or
                not isinstance(expected, str) or len(expected) != 40 or
                not isinstance(size, int) or size <= 0):
            raise ValueError("Invalid pinned source declaration")
        if tour == "wta":
            expected_path = f"data/wta/wta/{year}_wta.csv"
        elif tour == "atp_challenger":
            expected_path = f"data/atp/challenger/{year}_challenger.csv"
        else:
            expected_path = f"data/atp/atp/{year}.csv"
        if path != expected_path:
            raise ValueError("Source path does not match tour/year")
        seen_paths.add(path)
        raw = (root / path).read_bytes()
        if len(raw) != size or blob_sha1(raw) != expected:
            raise ValueError(f"SHA-pinned mirror source mismatch: {path}")
        text = raw.decode("utf-8-sig")
        from io import StringIO
        reader = csv.DictReader(StringIO(text, newline=""))
        header = reader.fieldnames or []
        if len(header) != len(set(header)) or not REQUIRED.issubset(header):
            raise ValueError(f"Missing or duplicate columns: {path}")
        native = defaultdict(list)
        file_counts = Counter()
        for row in reader:
            file_counts["raw"] += 1
            if None in row or any(v is None for v in row.values()):
                file_counts["rejected_shape"] += 1
                continue
            if (not valid_tourney_season_start(row, year)
                    or not row["tourney_id"]
                    or not row["match_num"].isascii()
                    or not row["match_num"].isdecimal()
                    or not ID.fullmatch(row["winner_id"] or "")
                    or not ID.fullmatch(row["loser_id"] or "")
                    or row["winner_id"] == row["loser_id"]
                    or not row["winner_name"] or not row["loser_name"]):
                file_counts["rejected_unverified_native_identity"] += 1
                continue
            native[(row["tourney_id"], row["match_num"])].append(row)
        ready: list[dict] = []
        for event_rows in native.values():
            if len(event_rows) != 1:
                file_counts["rejected_duplicate_native_event"] += len(event_rows)
                continue
            row = event_rows[0]
            if not complete_winner_score(row["score"], row["best_of"]):
                file_counts["rejected_unfinished_or_invalid_score"] += 1
                continue
            numbers = _numbers(row)
            if numbers is None:
                file_counts["rejected_impossible_stats"] += 1
                continue
            if not numbers:
                file_counts["rejected_without_stats"] += 1
                continue
            file_counts["qualified_source_rows"] += 1
            if len(numbers) == len(STATS):
                file_counts["qualified_all_count_fields"] += 1
            ready.append(row)
        output_file = output / (
            f"wta-{year}.csv" if tour == "wta" else
            f"atp-challenger-{year}.csv" if tour == "atp_challenger" else
            f"atp-tour-{year}.csv")
        with output_file.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=header)
            writer.writeheader()
            writer.writerows(ready)
        if sum(v for k, v in file_counts.items() if
               k.startswith("rejected_")) + file_counts["qualified_source_rows"] != file_counts["raw"]:
            raise ValueError(f"Source rows not accounted for: {path}")
        counts.update(file_counts)
        report_files.append({
            "file": path, "tour": tour, "year": year,
            "git_blob_sha": expected, "counts": dict(file_counts),
            "stage_file": output_file.name,
        })
    result = {
        "schema": 1,
        "state": "SOURCE_ONLY_QA_NO_CANONICAL_WRITE",
        "source_repo": manifest.get("source_repo"),
        "source_commit": manifest.get("pinned_commit"),
        "counts": dict(counts),
        "files": report_files,
        "source_event_id_attested_against_cdb": False,
        "cdb_write_authorized": False,
        "cdb_mutated": False,
        "api_requests": 0,
    }
    (output / "report.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args()
    print(json.dumps(prepare(a.source_dir, a.manifest, a.out_dir),
                     sort_keys=True))


if __name__ == "__main__":
    main()
