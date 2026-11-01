#!/usr/bin/env python3
"""SHA-pinned, source-only audit for the uploaded ATP 2025 enriched CSV.

This is NOT native Sackmann, despite Sackmann-style stat column labels.
Its opaque player, match, and tournament IDs MUST NOT be relabeled as
Sackmann or canonical provider IDs. Never creates import_ready records.
Only the existing verified crosswalk/linker and guarded CDB writer can
subsequently authorize NULL-only writes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SOURCE_ID_NAMESPACE = "uploaded-atp-2025-opaque"
MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 100_000
COUNT_FIELDS = ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon", "SvGms", "bpSaved", "bpFaced")
REQUIRED = {
    "tourney_id", "tourney_date", "tourney_name", "match_num", "match_id", "start_time_utc",
    "winner_id", "loser_id", "winner_name", "loser_name", "surface", "round", "score", "best_of",
    *(f"{side}_{field}" for side in ("w", "l") for field in COUNT_FIELDS),
}
SCORE_PART = re.compile(r"^(\d{1,2})-(\d{1,2})(?:\(\d{1,2}\))?$", re.ASCII)
SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def uint(value: str) -> int | None:
    v = str(value or "").strip()
    return int(v) if v.isascii() and v.isdecimal() else None


def game_score_quality(score: str, best_of: str) -> str:
    """Regular complete winner-oriented set scores only; retirements are review."""
    parts = str(score or "").strip().split()
    if not parts or str(best_of).strip() not in {"3", "5"}:
        return "score_or_format_missing"
    wins = losses = 0
    for part in parts:
        m = SCORE_PART.fullmatch(part)
        if not m:
            return "nonstandard_or_incomplete_score"
        w, l = int(m.group(1)), int(m.group(2))
        # Normal tiebreak and advantage sets (including final 10-8) permitted.
        if w == l or (max(w, l) < 6) or min(w, l) < 0 or max(w, l) > 70:
            return "impossible_score"
        wins += w > l
        losses += l > w
    need = (int(best_of) + 1) // 2
    if wins != need or wins <= losses or wins + losses > int(best_of):
        return "winner_score_conflict"
    return "valid"


def counts_quality(row: dict[str, str]) -> tuple[str, dict[str, dict[str, int]]]:
    counts = {side: {key: uint(row.get(f"{side}_{key}")) for key in COUNT_FIELDS}
              for side in ("w", "l")}
    for d in counts.values():
        if any(v is None for v in d.values()):
            return "incomplete_serve_counts", counts
        sv, fi, fw, sw = (d[k] for k in ("svpt", "1stIn", "1stWon", "2ndWon"))
        if (sv <= 0 or not 0 <= fi <= sv or not 0 <= fw <= fi
                or not 0 <= sw <= sv - fi or fw + sw > sv
                or d["ace"] > fw + sw or d["df"] > sv - fi
                or d["bpSaved"] > d["bpFaced"] or d["bpFaced"] > sv
                or d["SvGms"] <= 0 or d["SvGms"] > sv):
            return "invalid_serve_arithmetic", counts
    return "valid", counts


def rates(counts: dict[str, dict[str, int]]) -> dict[str, dict[str, float | int]]:
    out = {}
    for own, other in (("w", "l"), ("l", "w")):
        d, opp = counts[own], counts[other]
        second_den = d["svpt"] - d["1stIn"]
        own_stats = {
            "aces": d["ace"],
            "double_faults": d["df"],
            "service_points_won": (d["1stWon"] + d["2ndWon"]) / d["svpt"],
            "return_points_won": (opp["svpt"] - opp["1stWon"] - opp["2ndWon"]) / opp["svpt"],
        }
        if d["1stIn"] > 0:
            own_stats["first_serve_win"] = d["1stWon"] / d["1stIn"]
        if second_den > 0:
            own_stats["second_serve_win"] = d["2ndWon"] / second_den
        if d["bpFaced"] > 0:
            own_stats["break_point_serve_win"] = d["bpSaved"] / d["bpFaced"]
        if opp["bpFaced"] > 0:
            own_stats["break_point_return_win"] = (opp["bpFaced"] - opp["bpSaved"]) / opp["bpFaced"]
        out[own] = own_stats
    return out


def exact_time(row: dict[str, str]) -> datetime | None:
    try:
        original = str(row.get("start_time_utc") or "")
        if not original.endswith("Z"):
            return None
        instant = datetime.fromisoformat(original.replace("Z", "+00:00"))
        start = datetime.strptime(str(row.get("tourney_date") or ""), "%Y%m%d").date()
        if instant.tzinfo is None or instant.utcoffset().total_seconds() != 0:
            return None
        if not -1 <= (instant.date() - start).days <= 21:
            return None
        if not 2024 <= instant.year <= 2025:
            return None
        return instant
    except (ValueError, TypeError, OverflowError):
        return None


def prepare(source: Path, output: Path, expected_sha256: str) -> dict:
    if not SHA.fullmatch(expected_sha256):
        raise ValueError("A full immutable source SHA-256 is mandatory")
    if not source.is_file() or source.suffix.lower() != ".csv" or source.stat().st_size > MAX_BYTES:
        raise ValueError("Expected a bounded local CSV")
    if digest(source) != expected_sha256:
        raise ValueError("Uploaded source SHA-256 differs from pinned evidence")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Destination is not empty; never overwrite a source stage")
    output.mkdir(parents=True, exist_ok=True)
    summary = Counter()
    ids, events = set(), set()
    # All details remain local/private. Aggregated report is safe to log.
    with (output / "source_only.jsonl").open("w", encoding="utf-8") as accepted, \
         (output / "review.jsonl").open("w", encoding="utf-8") as review, \
         (output / "quarantine.jsonl").open("w", encoding="utf-8") as quarantine, \
         source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if not REQUIRED.issubset(fields) or len(fields) != len(set(fields)) or len(fields) > 128:
            raise ValueError("Unrecognized or duplicate enriched ATP 2025 columns")
        for line, row in enumerate(reader, 2):
            if summary["raw_rows"] >= MAX_ROWS or None in row or any(v is None for v in row.values()):
                raise ValueError("Malformed or oversized source CSV")
            summary["raw_rows"] += 1
            record = {"line": line, "source_record_id": f"{SOURCE_ID_NAMESPACE}:{expected_sha256}:{line}"}
            mid = str(row.get("match_id") or "").strip()
            tid = str(row.get("tourney_id") or "").strip()
            w = str(row.get("winner_id") or "").strip()
            l = str(row.get("loser_id") or "").strip()
            num = uint(row.get("match_num"))
            # A duplicate aborts the run without a completion manifest.
            # A partial temporary stage can never be consumed as complete.
            event = (tid, num)
            if mid in ids or event in events:
                raise ValueError("Duplicate source match ID or tournament/match key: fail closed")
            ids.add(mid)
            events.add(event)
            if (not all((mid, tid, w, l, num is not None, row.get("winner_name"), row.get("loser_name")))
                    or w == l or row["winner_name"] == row["loser_name"]):
                reason = "invalid_source_identity"
                quarantine.write(json.dumps({**record, "reason": reason}) + "\n")
                summary[reason] += 1
                continue
            event_time = exact_time(row)
            if event_time is None:
                reason = "missing_or_invalid_event_time"
                review.write(json.dumps({**record, "reason": reason}) + "\n")
                summary[reason] += 1
                continue
            score_state = game_score_quality(row.get("score"), row.get("best_of"))
            if score_state != "valid":
                review.write(json.dumps({**record, "reason": score_state}) + "\n")
                summary[score_state] += 1
                continue
            count_state, integers = counts_quality(row)
            if count_state != "valid":
                review.write(json.dumps({**record, "reason": count_state}) + "\n")
                summary[count_state] += 1
                continue
            if (not str(row.get("surface") or "").strip()
                    or not str(row.get("round") or "").strip()
                    or not str(row.get("tourney_name") or "").strip()):
                reason = "missing_context_surface_or_round"
                review.write(json.dumps({**record, "reason": reason}) + "\n")
                summary[reason] += 1
                continue
            derived = rates(integers)
            payload = {
                **record,
                "source_id_namespace": SOURCE_ID_NAMESPACE,
                "tour": "atp", "source_match_id": mid,
                "source_tourney_id": tid, "source_match_num": num,
                "source_winner_id": w, "source_loser_id": l,
                "winner_name": row["winner_name"], "loser_name": row["loser_name"],
                "tournament": row["tourney_name"], "surface": row["surface"],
                "round": row["round"], "score": row["score"],
                "tournament_start": row["tourney_date"],
                "source_event_time_utc": event_time.isoformat(),
                "date_kind": "source_claimed_match_start_not_independently_verified",
                "observations_winner": derived["w"], "observations_loser": derived["l"],
                "independent_canonical_identity_attested": False,
                "import_ready": False,
            }
            accepted.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            summary["source_only_complete_rows"] += 1
            summary["potential_stat_observations"] += sum(map(len, derived.values()))
    if digest(source) != expected_sha256:
        raise ValueError("Source changed during source-only staging")
    report = {
        "schema": "BLINQ_UPLOADED_ATP2025_SOURCE_ONLY_V1",
        "state": "SOURCE_ONLY_UNVERIFIED_PROVIDER_NAMESPACE",
        "source_sha256": expected_sha256,
        "source_id_namespace": SOURCE_ID_NAMESPACE,
        "source_date_kind": "uploaded claimed start_time_utc, not verified provider event time",
        "counts": dict(sorted(summary.items())),
        "source_only_file_sha256": digest(output / "source_only.jsonl"),
        "review_file_sha256": digest(output / "review.jsonl"),
        "quarantine_file_sha256": digest(output / "quarantine.jsonl"),
        "cdb_exact_linked": 0, "cdb_net_new": 0, "cdb_enriched_cells": 0,
        "cdb_write_authorized": False, "production_mutated": False,
        "api_requests": 0,
        "next_gate": "Independent source player/event ID crosswalk; current CDB SHA, exact winner/score/context, NULL-only dry-run with existing writer and remote read-back",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    report = prepare(args.source, args.out_dir, args.expected_sha256)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
