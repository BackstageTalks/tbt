#!/usr/bin/env python3
"""BlinQ 33-source-verified pilot: at most ONE NULL-only BP conversion cell.

The only allowed output is a post-match breakpoint conversion rate taken from
the independently pinned Sackmann source and cross-checked against the 33
private read-back-verified native ID links. There are no fuzzy joins, no
pre-match market values and no remote writes here. The workflow alone owns
the global writer lock, immutable backup, CAS and remote read-back.
"""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import csv
import hashlib
import json
from pathlib import Path
import re

from _bootstrap import ROOT  # noqa: F401
from audit_drive_atp_2020_2021_current_cdb import (
    SOURCE_IDS, IDENTITY_FIELDS, attest, get_rows, historical_event_id,
)
from offline_exact_cdb_write import write_exact_stats_partition
from recover_cdb_opponent_service_rates import _sha, _storage, verify_readback
from recover_cdb_sackmann_breakpoints import candidate, digest, POLICY, _source_rates, source_match_id, SOURCE_REVISION
from import_historical_match_foundation import _stats
from audit_cdb_sackmann_bp_count_gap import candidate as native_count_candidate, COUNTS
from tbt.data.history_snapshot import load_snapshot, partition_path

RELEASE_TAG = "blinq-drive-atp2020-2021-native-identity-39053414186-1"
VERIFIED_SHA = "e0945ee8437203b6db2e8a5e3e2eccc72e21df38a3a247925abc17eedc7c0935"
RATES = frozenset(("p1_break_point_return_win", "p2_break_point_return_win"))
COUNT_FIELDS = frozenset(COUNTS)
ALLOWED = RATES | COUNT_FIELDS
COUNT_POLICY = "sackmann_native_33_full_source_bp_converted_count_null_only_canary_v1"
SOURCE_COMMIT = "83733587353df8a41f2fd4f516147d5aa83f5a8d"

def verified_links(path: Path) -> list[dict]:
    if hashlib.sha256(path.read_bytes()).hexdigest() != VERIFIED_SHA:
        raise ValueError("Private 33-link readback receipt SHA changed")
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    if len(rows) != 33:
        raise ValueError("Private verified ID population is not exactly 33")
    keys = set()
    owners = set()
    for row in rows:
        if set(row) != {"tour", "source_namespace", "source_event_id", "canonical_match_id"}:
            raise ValueError("Unrecognized private ID sidecar fields")
        if row["tour"] != "atp" or row["source_namespace"] != "drive-atp-main-sackmann":
            raise ValueError("Unexpected source namespace")
        if (not isinstance(row["source_event_id"], str) or len(row["source_event_id"]) > 160
            or not re.fullmatch(r"[A-Za-z0-9_.:/-]+", row["source_event_id"])
            or row["source_event_id"].count(":") != 1
            or any(not part for part in row["source_event_id"].split(":"))):
            raise ValueError("Unexpected tournament-match event identifier")
        if not re.fullmatch(r"hist-js:atp:[a-f0-9]{24}", row["canonical_match_id"]):
            raise ValueError("Unexpected native canonical match ID")
        if row["source_event_id"] in keys or row["canonical_match_id"] in owners:
            raise ValueError("Duplicated private verified ID owner")
        keys.add(row["source_event_id"])
        owners.add(row["canonical_match_id"])
    return rows

def indexes(ledger: Path, original_dir: Path) -> tuple[dict, dict, dict]:
    rows = get_rows(ledger, delimiter="\t")
    if len(rows) != 2361:
        raise ValueError("Private original Drive identity ledger drift")
    proof = {}
    per_year = {}
    raw = {}
    for year in ("2020", "2021"):
        source = original_dir / ("atp_matches_" + year + ".csv")
        original = {}
        with source.open(encoding="utf-8-sig", newline="") as stream:
            for line_no, row in enumerate(csv.DictReader(stream), 2):
                key = row["tourney_id"] + ":" + row["match_num"]
                if key in original:
                    raise ValueError("Duplicate pinned original source event")
                original[key] = (row, line_no, source)
        raw[year] = original
        per_year[year] = digest(source)
    for row in rows:
        year = row["year"]
        if year not in SOURCE_IDS or row["drive_id"] != SOURCE_IDS[year]:
            raise ValueError("Unexpected original Drive source ID")
        key = row["tourney_id"] + ":" + row["match_num"]
        target = (year, key)
        if target in proof:
            raise ValueError("Duplicate Drive source key")
        original = raw[year].get(key)
        if not original:
            proof[target] = None
        elif all(row[f] == original[0][f] for f in IDENTITY_FIELDS):
            proof[target] = row
        else:
            proof[target] = None
    return proof, raw, per_year

def cdb_index(folder: Path) -> dict:
    result = {}
    for year in ("2020", "2021"):
        matches = load_snapshot(partition_path(folder, int(year)))
        if not matches:
            raise ValueError("Empty canonical partition")
        result[year] = {}
        for m in matches:
            if str(m.match_id) in result[year]:
                raise ValueError("Duplicate canonical match identity")
            result[year][str(m.match_id)] = m
    return result

def attested_rank_only_candidate(match, original: dict, path: Path, line_no: int, file_hash: str):
    """Narrow fallback ONLY after both event+player IDs and original file were proven.

    Older historical canonical rows may carry original-source _tbt_rank_provenance
    but no _tbt_statistics (stats were absent at original import). This is NOT
    a name/date join: stage() first reattests both native IDs and exact
    historical event marker against the separate 33-ID receipt + Drive ledger.
    """
    from datetime import datetime, timezone
    mid, kind = source_match_id("atp", path, original, line_no)
    original_source = "jeff_sackmann_match_snapshot:" + path.name
    ctx = match.provider_payload
    if (str(match.match_id) != mid or kind != "main"
        or not match.is_completed or str(match.status).lower() != "completed"
        or match.scheduled_at >= datetime.now(timezone.utc)
        or match.scheduled_at.strftime("%Y%m%d") != original.get("tourney_date")
        or str(match.player1_id) != "hist-js:atp:" + str(original.get("winner_id") or "")
        or str(match.player2_id) != "hist-js:atp:" + str(original.get("loser_id") or "")
        or str(match.winner_id) != str(match.player1_id)
        or not isinstance(ctx, dict)):
        return None, "rank_only_original_identity_conflict"
    marker = ctx.get("_tbt_statistics")
    if marker is not None:
        # No fallback if canonical already attributes stats to any source.
        return None, "canonical_stats_marker_present_no_rank_fallback"
    rank = ctx.get("_tbt_rank_provenance")
    if (not isinstance(rank, dict) or rank.get("source") != original_source):
        return None, "missing_original_rank_source_witness"
    rates = _source_rates(original)
    if not rates:
        return None, "invalid_or_zero_bp_denominator_rank_only"
    previous = match.stats
    if not isinstance(previous, dict):
        return None, "bad_canonical_stats_rank_only"
    import math
    for key, observed in _stats(original).items():
        current = previous.get(key)
        if current is not None and (
            isinstance(current, bool) or not isinstance(current, (int, float))
            or not math.isfinite(current) or abs(float(current)-observed)>1e-6
        ):
            return None, "rank_only_original_stats_conflict"
    for key, value in rates.items():
        current = previous.get(key)
        if current is not None and (
            isinstance(current, bool) or not isinstance(current, (int, float))
            or not math.isfinite(current) or abs(float(current)-value)>1e-6
        ):
            return None, "rank_only_existing_bp_conflict"
        opposite = "p2_break_point_serve_win" if key.startswith("p1_") else "p1_break_point_serve_win"
        other = previous.get(opposite)
        if other is not None and (
            isinstance(other, bool) or not isinstance(other, (int, float))
            or not math.isfinite(other) or abs(float(other)+value-1)>1e-6
        ):
            return None, "rank_only_existing_serve_counterpart_conflict"
    additions = {k:v for k,v in rates.items() if previous.get(k) is None}
    if not additions:
        return None, "rank_only_already_filled"
    return {
        "schema":1, "policy":POLICY, "match_id":mid,
        "utc_year":match.scheduled_at.year,
        "prewrite_hash":_sha(_storage(match)),
        "source_stats_hash":_sha(previous),
        "source":{
            "commit":SOURCE_REVISION, "file":path.as_posix(),
            "sha256":file_hash, "csv_line":line_no,
            "winner_id":str(original["winner_id"]), "loser_id":str(original["loser_id"]),
        },
        "additions":dict(sorted(additions.items())),
    }, "staged_attested_rank_only_original"

def stage(ledger: Path, verified: Path, original_dir: Path, history: Path) -> tuple[list, dict]:
    links = verified_links(verified)
    proof, raw, filesha = indexes(ledger, original_dir)
    canonical = cdb_index(history)
    stats = Counter()
    eligible = []
    verified_rechecked = set()
    for link in links:
        source_event = link["source_event_id"]
        year = source_event[:4]
        row = proof.get((year, source_event))
        original = raw[year].get(source_event)
        if row is None or original is None:
            raise ValueError("Previously verified source event no longer has original evidence")
        csv_row, line_no, path = original
        mid = link["canonical_match_id"]
        if historical_event_id(row) != mid:
            raise ValueError("Private sidecar event fingerprint disagrees with Drive original")
        m = canonical[year].get(mid)
        if m is None:
            raise ValueError("A previously verified canonical event is missing")
        checked = {
            "match_id": str(m.match_id), "tour": m.tour,
            "scheduled_at": m.scheduled_at.isoformat(),
            "player1_id": m.player1_id, "player2_id": m.player2_id,
            "player1_name": m.player1_name, "player2_name": m.player2_name,
            "winner_id": m.winner_id, "status": m.status,
            "provider_context_json": m.provider_payload,
        }
        if attest(row, checked) != "VERIFIED_NATIVE_EVENT_AND_BOTH_PLAYERS":
            raise ValueError("Previously verified CDB event lost original-source identity")
        verified_rechecked.add(mid)
        proposed, reason = candidate(m, csv_row, "atp", path, line_no, filesha[year])
        stats[reason] += 1
        if proposed is None and reason == "lineage_rejected":
            proposed, fallback_reason = attested_rank_only_candidate(m, csv_row, path, line_no, filesha[year])
            stats[fallback_reason] += 1
        if proposed is None and reason == "already_filled":
            # Existing rates are already in CDB; prefer exactly one original
            # integer converted BP count from the same SHA-pinned source.
            counts, count_reason = native_count_candidate(m, csv_row, "atp", "main", path)
            stats["count_" + count_reason] += 1
            if counts:
                proposed = {
                    "schema": 1, "policy": COUNT_POLICY,
                    "match_id": mid, "utc_year": m.scheduled_at.year,
                    "prewrite_hash": _sha(_storage(m)),
                    "source_stats_hash": _sha(m.stats or {}),
                    "source": {
                        "commit": SOURCE_REVISION, "file": path.as_posix(),
                        "sha256": filesha[year], "csv_line": line_no,
                        "winner_id": str(csv_row["winner_id"]),
                        "loser_id": str(csv_row["loser_id"]),
                    },
                    "additions": dict(sorted(counts.items())),
                }
        if proposed is None:
            continue
        if proposed["match_id"] != mid or proposed["policy"] not in (POLICY, COUNT_POLICY):
            raise ValueError("BP candidate identity or policy mismatch")
        for field, value in sorted(proposed["additions"].items()):
            if (field not in ALLOWED or type(value) not in (int, float)
                or (field in RATES and not 0 <= value <= 1)
                or (field in COUNT_FIELDS and (type(value) is not int or value < 0))):
                raise ValueError("Unapproved breakpoint rate")
            if m.stats.get(field) is not None:
                raise ValueError("BP proposed to overwrite present CDB field")
            row = copy.deepcopy(proposed)
            row["additions"] = {field: value}
            row["pilot"] = "blinq-native-33-single-cell-v1"
            eligible.append(row)
    if len(verified_rechecked) != 33:
        raise ValueError("Not all 33 verified CDB identities were independently rechecked")
    eligible.sort(key=lambda r: (r["utc_year"], r["match_id"], sorted(r["additions"])[0]))
    # Strict small canary, never widen to two matches or two cells.
    selected = eligible[:1]
    return selected, {
        "verified_eligible_id_population": len(verified_rechecked),
        "candidate_single_cells": len(eligible),
        "selected_single_cells": len(selected),
        "reason_counts": dict(sorted(stats.items())),
        "canonical_writes": 0,
        "existing_values_overwritten": 0,
        "import_scope": "ONE_POSTMATCH_BREAKPOINT_RATE_OR_CONVERTED_COUNT_NULL_ONLY",
    }

def load_stage(path: Path) -> list[dict]:
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    if len(rows) != 1 or rows[0].get("pilot") != "blinq-native-33-single-cell-v1":
        raise ValueError("Pilot must be one exact staged cell on one existing match")
    if (rows[0].get("policy") not in (POLICY, COUNT_POLICY) or rows[0].get("utc_year") not in (2020, 2021)
        or set(rows[0].get("additions", {})) - ALLOWED
        or len(rows[0].get("additions", {})) != 1):
        raise ValueError("Unapproved native single-cell write scope")
    field = next(iter(rows[0]["additions"]))
    if rows[0]["policy"] != (COUNT_POLICY if field in COUNT_FIELDS else POLICY):
        raise ValueError("Converted count/rate source policy mismatch")
    return rows

def exact_write(stage_rows: list[dict], history: Path) -> dict:
    row = stage_rows[0]
    year = row["utc_year"]
    before = load_snapshot(partition_path(history, year))
    after = copy.deepcopy(before)
    by_id = {str(x.match_id): x for x in after}
    if len(by_id) != len(after):
        raise ValueError("Duplicate canonical native ID")
    m = by_id.get(row["match_id"])
    if m is None or _sha(_storage(m)) != row["prewrite_hash"]:
        raise ValueError("Canonical row baseline mismatch")
    if _sha(m.stats or {}) != row["source_stats_hash"]:
        raise ValueError("Canonical stats baseline mismatch")
    for field, value in row["additions"].items():
        if (m.stats or {}).get(field) is not None:
            raise ValueError("Cannot overwrite non-NULL canonical field")
        if field not in ALLOWED or (field in RATES and not 0 <= value <= 1) or (field in COUNT_FIELDS and (type(value) is not int or value < 0)):
            raise ValueError("Invalid count/rate for pilot")
    m.stats = {**(m.stats or {}), **row["additions"]}
    info = write_exact_stats_partition(history, year, after, {row["match_id"]}, approved_count_fields=COUNT_FIELDS)
    readback = verify_readback(before, load_snapshot(partition_path(history, year)), stage_rows)
    if (readback["status"] != "verified" or readback["new_stat_values"] != 1
        or readback["existing_values_overwritten"] != 0
        or readback["enriched_matches"] != 1):
        raise ValueError("Local full-year CDB identity/value readback failed")
    return {"stage": row, "local": readback, "partition": info}

def independent_verify(before: Path, persisted: Path, stage_rows: list) -> dict:
    row = stage_rows[0]
    year = row["utc_year"]
    readback = verify_readback(
        load_snapshot(partition_path(before, year)),
        load_snapshot(partition_path(persisted, year)), stage_rows,
    )
    if (readback.get("status") != "verified" or readback.get("new_stat_values") != 1
        or readback.get("existing_values_overwritten") != 0
        or readback.get("enriched_matches") != 1):
        raise ValueError("Remote CDB one-cell readback mismatch")
    return {"state": "VERIFIED_ONE_CANONICAL_CDB_CELL", **readback, "year": year}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("stage", "write", "verify"), required=True)
    p.add_argument("--ledger", type=Path)
    p.add_argument("--verified", type=Path)
    p.add_argument("--source-dir", type=Path)
    p.add_argument("--history-dir", type=Path)
    p.add_argument("--before-dir", type=Path)
    p.add_argument("--stage-file", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.mode == "stage":
        if not all((a.ledger, a.verified, a.source_dir, a.history_dir)):
            p.error("stage requires ledger, verified sidecar, original source, current CDB")
        rows, counts = stage(a.ledger, a.verified, a.source_dir, a.history_dir)
        ledger_path = a.out.with_name("pilot-stage.jsonl")
        ledger_path.write_text("".join(json.dumps(x, sort_keys=True, allow_nan=False)+"\n" for x in rows))
        report = {"state": "PREFLIGHT_READONLY", "counts": counts,
                  "selected": 1 if rows else 0, "production_writes": 0}
    else:
        if not a.stage_file or not a.history_dir:
            p.error("write/verify requires --stage-file and --history-dir")
        rows = load_stage(a.stage_file)
        if a.mode == "write":
            if not a.ledger or not a.verified or not a.source_dir:
                p.error("write must reproduce the original immutable inputs")
            regenerated, _ = stage(a.ledger, a.verified, a.source_dir, a.history_dir)
            if regenerated != rows:
                raise ValueError("Dry-run stage differs from CDB/source recheck")
            report = {"state": "LOCAL_ONLY_ONE_CELL", **exact_write(rows, a.history_dir)}
        else:
            if not a.before_dir:
                p.error("verify requires --before-dir")
            report = independent_verify(a.before_dir, a.history_dir, rows)
    a.out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, default=str)+"\n")
    print(json.dumps({"state": report["state"], "counts": report.get("counts"),
                      "production_writes": 0 if a.mode != "verify" else 1}, sort_keys=True))

if __name__ == "__main__":
    main()
