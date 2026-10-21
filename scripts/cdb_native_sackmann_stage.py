#!/usr/bin/env python3
"""Native Jeff Sackmann CSV -> read-only CDB exact-linker input.

Original player IDs and tournament-start semantics survive unchanged.
Unlike generic Drive normalization this accepts only native yearly schemas.
Output is SOURCE_ONLY, never an independently verified CDB crosswalk.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

PATTERN = re.compile(
    r"^(atp|wta)_matches_(?:(qual_chall|futures|qual_itf)_)?(20[012]\d)\.csv$"
)
REQUIRED = {
    "tourney_date", "tourney_id", "match_num", "tourney_name",
    "winner_id", "loser_id", "winner_name", "loser_name",
    "surface", "round", "score", "best_of",
}
COUNTS = (
    "svpt", "1stIn", "1stWon", "2ndWon", "ace", "df", "bpSaved", "bpFaced",
)

def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _uint(value):
    token = str(value or "").strip()
    return int(token) if token.isdigit() else None

def _quality(row: dict) -> str:
    stats_exist = False
    for side in ("w", "l"):
        d = {key: _uint(row.get(f"{side}_{key}")) for key in COUNTS}
        stats_exist |= any(v is not None for v in d.values())
        s, a, b, c = (d[k] for k in ("svpt", "1stIn", "1stWon", "2ndWon"))
        if (s is None or s <= 0 or a is None or b is None or c is None
                or b > a or a > s or c > s - a or b + c > s):
            return "INCOMPLETE_OR_INVALID" if stats_exist else "NO_STATS"
        if (d["bpSaved"] is not None and d["bpFaced"] is not None
                and d["bpSaved"] > d["bpFaced"]):
            return "INCOMPLETE_OR_INVALID"
    return "COMPLETE_BASIC_SERVE_RETURN"

def prepare(source_root: Path, output_dir: Path, start_year: int = 2016,
            end_year: int = 2026) -> dict:
    if not source_root.is_dir() or not 1968 <= start_year <= end_year <= 2026:
        raise ValueError("Invalid native input folder or year window")
    output_dir.mkdir(parents=True, exist_ok=True)
    linker_dir = output_dir / "native_linker_input"
    linker_dir.mkdir(exist_ok=True)
    metrics = Counter()
    files = []
    for path in sorted(source_root.rglob("*.csv")):
        m = PATTERN.fullmatch(path.name)
        if not m: continue
        tour, family, year = m.group(1), m.group(2) or "main", int(m.group(3))
        if not start_year <= year <= end_year: continue
        if (tour == "atp" and family == "qual_itf") or (tour == "wta" and family in {"qual_chall", "futures"}):
            raise ValueError("Unexpected native source family")
        digest = _digest(path)
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not REQUIRED.issubset(reader.fieldnames or []):
                raise ValueError(f"Not a native Sackmann match table: {path.name}")
            # Tour/season/family and source file SHA disambiguate provider keys.
            # A source tournament ID + match_num can repeat; never resolve
            # such rows to a canonical CDB match automatically.
            rows = list(reader)
        occurrences = Counter((r.get("tourney_id"), r.get("match_num")) for r in rows)
        output = linker_dir / f"{tour}_{family}_{year}_{digest[:16]}.csv"
        accepted = 0
        with output.open("w", encoding="utf-8", newline="") as handle:
            fields = list(reader.fieldnames or []) + ["league", "source_record_id"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for index, row in enumerate(rows, 2):
                metrics["raw_match_rows"] += 1
                if occurrences[(row.get("tourney_id"), row.get("match_num"))] != 1:
                    metrics["quarantined_ambiguous_native_match_key"] += 1
                    continue
                if (not row.get("winner_id") or not row.get("loser_id")
                        or row["winner_id"] == row["loser_id"]
                        or not row.get("winner_name") or not row.get("loser_name")
                        or not re.fullmatch(r"\d{8}", str(row.get("tourney_date") or ""))):
                    metrics["quarantined_identity_or_tournament_start"] += 1
                    continue
                quality = _quality(row)
                metrics[quality] += 1
                if quality != "COMPLETE_BASIC_SERVE_RETURN":
                    continue
                row["league"] = tour
                row["source_record_id"] = f"sackmann:{tour}:{family}:{year}:{digest}:{index}"
                writer.writerow(row)
                accepted += 1
        metrics["linker_ready_source_rows"] += accepted
        files.append({
            "native_filename": path.name, "source_sha256": digest,
            "tour": tour, "source_family": family, "season": year,
            "raw_rows": len(rows), "linker_ready_rows": accepted,
            "linker_csv": str(output.resolve()),
            "linker_csv_sha256": _digest(output),
        })
    report = {
        "schema": "BLINQ_SACKMANN_NATIVE_STAGE_V1",
        "state": "SOURCE_ONLY", "production_mutated": False, "api_requests": 0,
        "canonical_matches_written": 0, "canonical_stat_fields_written": 0,
        "source_license": "CC BY-NC-SA 4.0; commercial rights require separate verification",
        "date_kind": "tourney_date_is_tournament_start_not_exact_match_day",
        "source_id_namespace": "sackmann:{tour}",
        "canonical_id_attested": False, "canonical_write_authorized": False,
        "counts": dict(sorted(metrics.items())), "files": files,
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--start-year", type=int, default=2016)
    p.add_argument("--end-year", type=int, default=2026)
    args = p.parse_args()
    report = prepare(args.source_root, args.out_dir, args.start_year, args.end_year)
    print(json.dumps({"state": report["state"], "counts": report["counts"],
                      "native_source_files": len(report["files"])}, sort_keys=True))

if __name__ == "__main__":
    main()
