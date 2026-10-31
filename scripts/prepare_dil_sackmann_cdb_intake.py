#!/usr/bin/env python3
"""Read-only DIL Sackmann source -> private, verified-ID linker-input preflight.

No canonical CDB writes. No name/date identity inference. This script never
labels a row import_ready; independent cross-provider IDs and a fresh CDB
NULL-only dry-run are still required by the existing guarded importer.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import sqlite3

TABLES = {
    "dil_sackmann_source_files", "dil_sackmann_source_observations",
    "dil_sackmann_provenance", "dil_sackmann_intake_decisions",
    "dil_sackmann_verified_preexisting_links", "dil_sackmann_receipts",
}
FILE_PATTERN = re.compile(r"(atp|wta)_matches_(\d{4})\.csv\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
STAT_FIELDS = ("svpt", "1stIn", "1stWon", "2ndWon", "ace", "df", "bpFaced", "bpSaved")


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def unsigned(value):
    if isinstance(value, bool):
        return None
    token = str(value if value is not None else "").strip()
    return int(token) if token.isdecimal() else None


def side_valid(raw: dict, prefix: str) -> bool:
    d = {key: unsigned(raw.get(f"{prefix}_{key}")) for key in STAT_FIELDS}
    total, first, first_won, second_won = (d[k] for k in ("svpt", "1stIn", "1stWon", "2ndWon"))
    if (None in (total, first, first_won, second_won)
            or not 0 < first < total or first_won > first
            or second_won > total - first or first_won + second_won > total):
        return False
    if d["ace"] is not None and d["ace"] > total:
        return False
    if d["df"] is not None and d["df"] > total - first:
        return False
    faced, saved = d["bpFaced"], d["bpSaved"]
    if (faced is None) != (saved is None) or (faced is not None and saved > faced):
        return False
    return True


def score_complete(score: str) -> bool:
    value = str(score or "").upper()
    return bool(re.search(r"\d{1,2}-\d{1,2}", value)) and not any(
        x in value for x in ("RET", "W/O", "WALKOVER", "DEF", "ABD", "INT", "CANC")
    )


def _source_index(db: sqlite3.Connection) -> dict[str, tuple[str, int, str, int]]:
    sources = {}
    for name, sha, tour, year, rows in db.execute(
        "SELECT filename,sha256,tour,year,row_count FROM dil_sackmann_source_files"
    ):
        match = FILE_PATTERN.fullmatch(name or "")
        if (not match or tour != match[1] or year != int(match[2])
                or not isinstance(sha, str) or not HEX64.fullmatch(sha)
                or name in sources or not isinstance(rows, int) or rows < 0):
            raise ValueError("Bad DIL Sackmann file inventory")
        sources[name] = (sha, year, tour, rows)
    return sources


def prepare(source: Path, output: Path, expected_sha256: str, *, start_year=2016, end_year=2026) -> dict:
    if not source.is_file() or not HEX64.fullmatch(expected_sha256 or ""):
        raise ValueError("SHA-pinned DIL source-only SQLite required")
    actual_sha = digest(source)
    if actual_sha != expected_sha256:
        raise ValueError("DIL source extension SHA-256 mismatch")
    if output.exists() or not 1968 <= start_year <= end_year <= 2026:
        raise ValueError("Output must not exist and year window must be valid")

    db = sqlite3.connect(source.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    grouped: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    counts = Counter()
    by_season = defaultdict(Counter)
    try:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not TABLES.issubset(tables):
            raise ValueError("DIL Sackmann source extension tables missing")
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("SQLite integrity check failed")
        receipts = dict(db.execute("SELECT key,value FROM dil_sackmann_receipts"))
        if (json.loads(receipts.get("state", 'null')) != "ISOLATED_SOURCE_ONLY_CDB_PARITY_BLOCKED"
                or receipts.get("provenance_join_to_observation_verified") != "false"
                or receipts.get("production_CDB_modified") != "false"):
            raise ValueError("Unapproved or misunderstood DIL source-only snapshot")
        source_files = _source_index(db)
        if not source_files:
            raise ValueError("Missing source files")
        preexisting = db.execute('''SELECT count(*),
            coalesce(sum(already_present_stat_values),0), coalesce(sum(new_stat_values),0)
            FROM dil_sackmann_verified_preexisting_links''').fetchone()
        if (preexisting[0] != int(receipts.get("verified_already_present", -1))
                or preexisting[2] != 0 or receipts.get("canonical_new_metric_values") != "0"):
            raise ValueError("Preexisting-only link receipt mismatch or unauthorized new stats")
        counts["preexisting_verified_links"] = preexisting[0]
        counts["preexisting_stat_values_reused"] = preexisting[1]
        observed_by_file = Counter()
        seen_origin = set()
        for name, line, tour, year, row_sha, winner, loser, tournament, identity_status, raw_text in db.execute('''
            SELECT source_file,source_row,tour,file_year,row_sha256,
                   winner_id,loser_id,tourney_id,identity_status,raw_json
            FROM dil_sackmann_source_observations ORDER BY source_file,source_row'''):
            counts["all_source_rows"] += 1
            meta = source_files.get(name)
            if (meta is None or meta[1] != year or meta[2] != tour
                    or not isinstance(line, int) or line < 2
                    or not isinstance(row_sha, str) or not HEX64.fullmatch(row_sha)
                    or (name, line) in seen_origin):
                raise ValueError("Inconsistent or duplicate source observation identity")
            seen_origin.add((name, line))
            observed_by_file[name] += 1
            try:
                raw = json.loads(raw_text)
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid original source JSON") from exc
            if not isinstance(raw, dict) or any(
                str(raw.get(k) or "") != str(v or "") for k, v in (
                    ("winner_id", winner), ("loser_id", loser), ("tourney_id", tournament)
                )
            ):
                raise ValueError("Original source row differs from observation columns")
            if year < start_year or year > end_year:
                continue
            counts["window_source_rows"] += 1
            by_season[(tour, year)]["source_rows"] += 1
            if not score_complete(raw.get("score")):
                counts["noncompleted_or_uncertain_score"] += 1
                by_season[(tour, year)]["noncompleted_or_uncertain_score"] += 1
                continue
            if not (side_valid(raw, "w") and side_valid(raw, "l")):
                counts["serve_incomplete_or_invalid"] += 1
                by_season[(tour, year)]["serve_incomplete_or_invalid"] += 1
                continue
            counts["source_valid_two_sided_serve"] += 1
            by_season[(tour, year)]["source_valid_two_sided_serve"] += 1
            if all(unsigned(raw.get(f"{side}_{key}")) is not None
                   for side in ("w", "l") for key in ("bpFaced", "bpSaved")):
                counts["source_valid_two_sided_breakpoints"] += 1
            # Never invent external player or event IDs. Without all three,
            # preserve the source in DIL review, not a canonical/linker stage.
            if (identity_status != "NATIVE_IDS_COMPLETE" or
                    not all(str(v or "").strip() for v in (winner, loser, tournament))):
                counts["review_missing_native_identity"] += 1
                by_season[(tour, year)]["review_missing_native_identity"] += 1
                continue
            # This is still ONLY an input to an independently verified
            # crosswalk linker, not a CDB-ready import candidate.
            raw = dict(raw)
            raw["source_record_id"] = f"dil:{meta[0]}:{line}:{row_sha}"
            grouped[name].append((line, raw))
            counts["linker_input_rows_pending_independent_crosswalk"] += 1
        if any(observed_by_file.get(name, 0) != meta[3] for name, meta in source_files.items()):
            raise ValueError("Stored source file row counts disagree with observations")
        if counts["all_source_rows"] != int(receipts.get("source_observations", -1)):
            raise ValueError("Source receipt row count mismatch")
        if db.execute("SELECT count(*) FROM dil_sackmann_provenance").fetchone()[0] != int(
                receipts.get("sources_metadata_provenance", -1)):
            raise ValueError("Provenance source count mismatch")
    finally:
        db.close()

    output.mkdir(parents=True, exist_ok=False)
    linker_dir = output / "linker_inputs"
    linker_dir.mkdir()
    try:
        for name, rows in sorted(grouped.items()):
            fields = sorted({field for _, raw in rows for field in raw})
            with (linker_dir / name).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
                writer.writeheader()
                for _, raw in sorted(rows):
                    writer.writerow(raw)
        report = {
            "schema": "DIL_SACKMANN_CDB_INTAKE_PREFLIGHT_V1",
            "state": "SOURCE_ONLY_NOT_CDB_IMPORT_AUTHORIZED",
            "dil_source_extension_sha256": actual_sha,
            "dil_provenance_join_attested": False,
            "canonical_cdb_sha256_verified": False,
            "canonical_identity_crosswalk_verified": False,
            "cdb_null_only_import_ready": 0,
            "production_cdb_modified": False,
            "model_or_serving_modified": False,
            "year_window": [start_year, end_year],
            "counts": dict(counts),
            "by_season": [dict(tour=tour, year=year, **dict(vals)) for (tour, year), vals in sorted(by_season.items())],
            "private_linker_input_files": sorted(grouped),
            "next_gate": "Fresh SHA-pinned canonical CDB; independently verified two-player crosswalk + primary event, winner orientation; strict existing linker; NULL-only dry-run; single-writer CAS and remote readback.",
        }
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report
    except Exception:
        # No silently partial output on writer errors.
        import shutil
        shutil.rmtree(output)
        raise


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-extension", type=Path, required=True)
    p.add_argument("--expected-source-sha256", required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--start-year", type=int, default=2016)
    p.add_argument("--end-year", type=int, default=2026)
    args = p.parse_args()
    result = prepare(args.source_extension, args.out_dir, args.expected_source_sha256,
                     start_year=args.start_year, end_year=args.end_year)
    print(json.dumps({k: result[k] for k in ("state", "counts", "cdb_null_only_import_ready")}, sort_keys=True))


if __name__ == "__main__":
    main()
