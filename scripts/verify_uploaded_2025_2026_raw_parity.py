#!/usr/bin/env python3
"""Fail-closed proof that a pinned normalized source stage equals operator-uploaded raw CSV.

Only checks source parity. Never authorizes a canonical identity or production write.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import zipfile
from pathlib import Path


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def as_int(row: dict, key: str) -> int | None:
    try:
        raw = row[key]
        if not raw:
            return None
        value = int(raw)
        return value if value >= 0 else None
    except (KeyError, TypeError, ValueError):
        return None


def rates(row: dict, prefix: str) -> dict:
    n, a, b, c = (as_int(row, f"{prefix}_{key}") for key in (
        "svpt", "1stIn", "1stWon", "2ndWon"))
    valid = all(x is not None for x in (n, a, b, c)) and (
        n > 0 and 0 <= b <= a <= n and 0 <= c <= n - a)
    result = {}
    for target, key in (("aces", "ace"), ("double_faults", "df")):
        value = as_int(row, f"{prefix}_{key}")
        if value is not None:
            result[target] = float(value)
    if valid:
        if a:
            result["first_serve_win"] = b / a
        if n - a:
            result["second_serve_win"] = c / (n - a)
        result["service_points_won"] = (b + c) / n
    faced = as_int(row, f"{prefix}_bpFaced")
    saved = as_int(row, f"{prefix}_bpSaved")
    if faced and saved is not None and saved <= faced:
        result["break_point_serve_win"] = saved / faced
    return result


def verify(raw_zip: Path, stage_path: Path, expected_raw: str, expected_stage: str) -> dict:
    raw_bytes = raw_zip.read_bytes()
    stage_bytes = stage_path.read_bytes()
    if sha256(raw_bytes) != expected_raw or sha256(stage_bytes) != expected_stage:
        raise ValueError("Untrusted raw ZIP or normalized stage SHA256")
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
        if archive.testzip() is not None:
            raise ValueError("Raw ZIP member CRC invalid")
        audit = json.loads(archive.read("audit/qa_report.json"))
        if audit["four_match_files_rows"] != 10927 or audit["closing_odds_rows"] != 5791:
            raise ValueError("Uploaded raw-source counts are not pinned")
        if len(audit["files"]) != 5:
            raise ValueError("Unexpected uploaded file inventory")
        originals = {}
        for name, metadata in audit["files"].items():
            data = archive.read("raw/" + name)
            if sha256(data) != metadata["sha256"]:
                raise ValueError("Raw ZIP per-file digest mismatch " + name)
            if name.startswith("atp_wta_"):
                continue
            tour = name.split("_", 1)[0].upper()
            for row in csv.DictReader(io.StringIO(data.decode("utf-8-sig"))):
                key = (tour, row["match_id"])
                if not row["match_id"] or key in originals:
                    raise ValueError("Raw duplicate event key")
                originals[key] = row
    if len(originals) != 10927:
        raise ValueError("Untrusted unique original events")

    matches, cells, seen = 0, 0, set()
    with gzip.open(io.BytesIO(stage_bytes), "rt", encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            item = json.loads(line)
            key = (item["source_tour"], item["source_match_id"])
            if key in seen or key not in originals:
                raise ValueError("Duplicate or missing normalized source key")
            seen.add(key)
            raw = originals[key]
            for normalized, field in (
                ("source_winner_id", "winner_id"),
                ("source_loser_id", "loser_id"),
                ("scheduled_at_utc", "start_time_utc"),
                ("source_score", "score"),
                ("source_tournament_name", "tourney_name"),
                ("source_tournament_id", "tourney_id"),
                ("source_surface", "surface"),
                ("source_round", "round"),
                ("source_best_of", "best_of"),
            ):
                if str(item[normalized]) != str(raw[field]):
                    raise ValueError(f"Raw-stage event identity conflict: {key} {field}")

            own = {prefix: rates(raw, prefix) for prefix in ("w", "l")}
            for prefix, side, opposite in (
                ("w", "winner", "l"), ("l", "loser", "w")
            ):
                expected = dict(own[prefix])
                if "service_points_won" in own[opposite]:
                    expected["return_points_won"] = 1 - own[opposite]["service_points_won"]
                faced = as_int(raw, f"{opposite}_bpFaced")
                saved = as_int(raw, f"{opposite}_bpSaved")
                if faced and saved is not None and saved <= faced:
                    expected["break_point_return_win"] = (faced - saved) / faced
                values = item[side + "_stats"]
                for field, value in values.items():
                    if field not in expected or not math.isclose(
                        value, expected[field], abs_tol=1.00001e-9, rel_tol=0
                    ):
                        raise ValueError(f"Raw-stage statistic conflict: {key} {side} {field}")
                    cells += 1
            matches += 1
    if matches != 9741 or cells != 154342:
        raise ValueError(f"Unexpected stage coverage {matches} rows {cells} stats")
    return {
        "schema": 1,
        "status": "VERIFIED_RAW_TO_SOURCE_STAGE_ONLY",
        "source_sha256": expected_raw,
        "stage_sha256": expected_stage,
        "raw_matches": len(originals),
        "verified_stage_matches": matches,
        "verified_stat_fields": cells,
        "excluded_unmatched_raw_events": len(originals) - matches,
        "closing_odds_pit_eligible": 0,
        "canonical_writes": 0,
        "identity_proven_to_cdb": False,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-zip", type=Path, required=True)
    ap.add_argument("--stage", type=Path, required=True)
    ap.add_argument("--raw-sha256", required=True)
    ap.add_argument("--stage-sha256", required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    result = verify(args.raw_zip, args.stage, args.raw_sha256, args.stage_sha256)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
