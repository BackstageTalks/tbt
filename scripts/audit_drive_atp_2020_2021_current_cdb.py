#!/usr/bin/env python3
"""Fail-closed Drive ATP 2020/21 native-event CDB reconciliation (READ ONLY).

The Drive source identity ledger is PRIVATE and pinned by Git blob ID. The
original Sackmann archive is pinned independently and must agree field-by-field
before any canonical match may be asserted. The current canonical Parquet
must contain the historical importer event ID, both original player IDs and
the exact preserved original-source event provenance. No canonical writes.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import unicodedata

FIELDS = (
    "year", "drive_id", "source_line", "tourney_id", "match_num",
    "tourney_date", "winner_id", "loser_id", "winner_name", "loser_name",
    "tourney_name", "round", "score",
)
IDENTITY_FIELDS = (
    "tourney_id", "match_num", "tourney_date", "winner_id", "loser_id",
    "winner_name", "loser_name", "tourney_name", "round", "score",
)
REQUIRED_CDB = (
    "match_id", "tour", "scheduled_at", "player1_id", "player2_id",
    "player1_name", "player2_name", "winner_id", "round_name",
    "provider_context_json", "status",
)
SOURCE_IDS = {
    "2020": "1_sJoqU9_7buu1R6E7frRrsqYFTdtkI1b",
    "2021": "1aSUtgsjogX4qY5C7hmIeDb7Cts8A5bmH",
}
ROUND_ALIASES = {
    "final": "f", "the final": "f", "semifinal": "sf",
    "semifinals": "sf", "quarterfinal": "qf", "quarterfinals": "qf",
    "round of 16": "r16", "round of 32": "r32", "round of 64": "r64",
    "round of 128": "r128", "round robin": "rr",
}

def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower().replace("_", " "))
    return " ".join(text.split())

def historical_event_id(row: dict) -> str:
    players = sorted((norm(row["winner_name"]), norm(row["loser_name"])))
    round_code = ROUND_ALIASES.get(norm(row["round"]), norm(row["round"]))
    if not all((row.get("tourney_id"), row.get("match_num"), round_code, *players)):
        raise ValueError("Incomplete historical event key")
    key = "|".join((
        "atp", "main", row["tourney_id"], row["match_num"], round_code,
        "|".join(players),
    ))
    return "hist-js:atp:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]

def source_key(row: dict) -> tuple[str, str]:
    return row["tourney_id"], row["match_num"]

def get_rows(path: Path, *, delimiter: str) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file, delimiter=delimiter)
        if delimiter == "\t" and tuple(reader.fieldnames or []) != FIELDS:
            raise ValueError("Identity ledger header drift")
        rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("Malformed source CSV")
    return rows

def load_originals(ledger: list[dict], source_dir: Path) -> tuple[dict, Counter]:
    originals = {}
    counts = Counter()
    for year, expected_rows in (("2020", 1462), ("2021", 899)):
        p = source_dir / ("atp_matches_" + year + ".csv")
        rows = get_rows(p, delimiter=",")
        originals[year] = {}
        for row in rows:
            key = source_key(row)
            if key in originals[year]:
                raise ValueError("Pinned source duplicate key")
            originals[year][key] = row
        counts[year + "_pinned_source_rows"] = len(rows)
        if len(rows) < expected_rows:
            raise ValueError("Pinned original unexpectedly incomplete")
    if len(ledger) != 2361:
        raise ValueError("Expected all 2361 audited Drive source rows")
    seen = set()
    for row in ledger:
        year = row["year"]
        if year not in SOURCE_IDS or row["drive_id"] != SOURCE_IDS[year]:
            raise ValueError("Unrecognized or altered Drive source ID")
        key = (year, *source_key(row))
        if key in seen:
            raise ValueError("Duplicate Drive source event")
        seen.add(key)
        pinned = originals[year].get(source_key(row))
        if not pinned:
            counts["missing_pinned_original"] += 1
        elif all(row[f] == pinned[f] for f in IDENTITY_FIELDS):
            counts["exact_original_event_witness"] += 1
        else:
            counts["original_identity_or_version_difference"] += 1
    if sum(1 for r in ledger if r["year"] == "2020") != 1462:
        raise ValueError("Unexpected Drive 2020 row count")
    if sum(1 for r in ledger if r["year"] == "2021") != 899:
        raise ValueError("Unexpected Drive 2021 row count")
    return originals, counts

def attest(row: dict, canonical: dict | None) -> str:
    if canonical is None:
        return "CANONICAL_EVENT_NOT_PRESENT"
    native = historical_event_id(row)
    if str(canonical.get("match_id")) != native:
        return "CANONICAL_EVENT_ID_MISMATCH"
    if norm(canonical.get("tour")) != "atp":
        return "CANONICAL_TOUR_MISMATCH"
    p1, p2 = ("hist-js:atp:" + row["winner_id"],
              "hist-js:atp:" + row["loser_id"])
    if not row["winner_id"] or not row["loser_id"] or p1 == p2:
        return "SOURCE_PLAYER_IDS_INVALID"
    if (str(canonical.get("player1_id")) != p1
            or str(canonical.get("player2_id")) != p2
            or str(canonical.get("winner_id")) != p1):
        return "CANONICAL_PLAYER_OR_WINNER_ID_MISMATCH"
    if (norm(canonical.get("player1_name")) != norm(row["winner_name"])
            or norm(canonical.get("player2_name")) != norm(row["loser_name"])):
        return "CANONICAL_PLAYER_NAME_CONFLICT"
    date = row["tourney_date"]
    if not re.fullmatch(r"\d{8}", date or ""):
        return "INVALID_SOURCE_TOURNAMENT_DATE"
    stamp = str(canonical.get("scheduled_at") or "")[:10].replace("-", "")
    if date != stamp:
        return "CANONICAL_DATE_CONFLICT"
    if norm(canonical.get("status")) != "completed":
        return "CANONICAL_NOT_COMPLETED"
    try:
        payload = canonical["provider_context_json"]
        ctx = payload if isinstance(payload, dict) else json.loads(payload)
    except (ValueError, TypeError, KeyError):
        return "CANONICAL_PROVENANCE_NOT_READABLE"
    if not isinstance(ctx, dict):
        return "CANONICAL_PROVENANCE_NOT_OBJECT"
    event = ctx.get("_tbt_event_identity")
    if (ctx.get("_tbt_provider_event_id") != native
            or ctx.get("_tbt_source_category_name") != "historical_main"
            or not isinstance(event, dict)
            or event.get("event_id") != native
            or norm(event.get("home")) != norm(row["winner_name"])
            or norm(event.get("away")) != norm(row["loser_name"])
            or event.get("status") != "completed"):
        return "CANONICAL_ORIGINAL_EVENT_LINEAGE_NOT_PROVEN"
    source_name = "jeff_sackmann_match_snapshot:atp_matches_" + row["year"] + ".csv"
    stats = ctx.get("_tbt_statistics")
    rank = ctx.get("_tbt_rank_provenance")
    if not ((isinstance(stats, dict) and stats.get("source") == source_name
             and stats.get("event_id") == native)
            or (isinstance(rank, dict) and rank.get("source") == source_name)):
        return "CANONICAL_SOURCE_FILE_PROVENANCE_NOT_PROVEN"
    return "VERIFIED_NATIVE_EVENT_AND_BOTH_PLAYERS"

def reconcile(ledger: list[dict], originals: dict, canonical_by_year: dict) -> dict:
    counts = Counter()
    claimed = defaultdict(list)
    observations = []
    for row in ledger:
        year = row["year"]
        pinned = originals[year].get(source_key(row))
        identity = {
            "tour": "atp", "source_namespace": "drive-atp-main-sackmann",
            "source_event_id": row["tourney_id"] + ":" + row["match_num"],
        }
        if pinned is None:
            status, mid = "MISSING_PINNED_SOURCE_EVENT", None
        elif any(row[f] != pinned[f] for f in IDENTITY_FIELDS):
            status, mid = "SOURCE_ARCHIVE_IDENTITY_DIFFERENCE_REVIEW", None
        else:
            mid = historical_event_id(row)
            status = attest(row, canonical_by_year[year].get(mid))
        if status == "VERIFIED_NATIVE_EVENT_AND_BOTH_PLAYERS":
            claimed[mid].append(identity["source_event_id"])
        counts[status] += 1
        observations.append({
            "source": identity, "drive_id": row["drive_id"],
            "source_line": int(row["source_line"]),
            "canonical_match_id": mid if status == "VERIFIED_NATIVE_EVENT_AND_BOTH_PLAYERS" else None,
            "status": "verified_link" if status == "VERIFIED_NATIVE_EVENT_AND_BOTH_PLAYERS" else "hold",
            "reason": status, "write_authorized": False,
        })
    for obs in observations:
        mid = obs["canonical_match_id"]
        if mid and len(claimed[mid]) != 1:
            obs["reason"], obs["status"], obs["canonical_match_id"] = (
                "CANONICAL_TARGET_COLLISION_REVIEW", "hold", None)
    counts = Counter(x["reason"] for x in observations)
    verified = [{
        **x["source"], "canonical_match_id": x["canonical_match_id"]
    } for x in observations if x["status"] == "verified_link"]
    if len(set((x["tour"], x["source_namespace"], x["source_event_id"]) for x in verified)) != len(verified):
        raise ValueError("Nonunique source identity sidecar")
    if len(set(x["canonical_match_id"] for x in verified)) != len(verified):
        raise ValueError("Nonunique canonical identity sidecar")
    return {
        "schema": "BLINQ_DRIVE_ATP_2020_2021_NATIVE_CDB_READONLY_V1",
        "counts": dict(sorted(counts.items())),
        "source_rows": len(ledger),
        "verified_ids": len(verified),
        "production_cdb_writes": 0,
        "bulk_import_authorized": False,
        "verified_secondary_ids": verified,
        "per_event": observations,
    }

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ledger", type=Path, required=True)
    p.add_argument("--pinned-source-dir", type=Path, required=True)
    p.add_argument("--cdb-dir", type=Path, required=True)
    p.add_argument("--release-json", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    import pyarrow.parquet as pq
    release = json.loads(a.release_json.read_text())
    assets = {item["name"]: item for item in release["assets"]}
    manifest_file = a.cdb_dir / "history_manifest.json"
    mhash = hashlib.sha256(manifest_file.read_bytes()).hexdigest()
    if assets["history_manifest.json"]["digest"] != "sha256:" + mhash:
        raise ValueError("Canonical manifest SHA does not match release")
    manifest = json.loads(manifest_file.read_text())
    cdb_by_year = {}
    pins = {}
    for year in ("2020", "2021"):
        name = "history-" + year + ".parquet"
        target = a.cdb_dir / name
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        meta = manifest["years"][year]
        if (assets[name]["digest"] != "sha256:" + digest
                or meta["sha256"] != digest or meta["bytes"] != target.stat().st_size):
            raise ValueError("Canonical Parquet digest/manifest mismatch " + year)
        pf = pq.ParquetFile(target)
        cols = set(pf.schema_arrow.names)
        if not set(REQUIRED_CDB).issubset(cols):
            raise ValueError("Canonical required fields missing " + str(set(REQUIRED_CDB)-cols))
        index = {}
        for row in pf.read(columns=list(REQUIRED_CDB)).to_pylist():
            mid = str(row.get("match_id") or "")
            if mid in index:
                raise ValueError("Duplicate canonical match_id")
            index[mid] = row
        cdb_by_year[year] = index
        pins[year] = {"sha256": digest, "canonical_rows": len(index)}
    ledger = get_rows(a.ledger, delimiter="\t")
    originals, evidence = load_originals(ledger, a.pinned_source_dir)
    result = reconcile(ledger, originals, cdb_by_year)
    result["source_crosscheck"] = dict(evidence)
    result["cdb_year_pins"] = pins
    result["canonical_manifest_sha256"] = mhash
    result["source_ledger_git_blob_sha1_verified_by_workflow"] = True
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    sidecar = a.out.with_name("verified-secondary-ids.jsonl")
    sidecar.write_text("".join(json.dumps(row, sort_keys=True) + "\n"
                              for row in result["verified_secondary_ids"]))
    print("DRIVE_ATP_NATIVE_CDB_READONLY", json.dumps({
        "source_rows": result["source_rows"], "verified_ids": result["verified_ids"],
        "counts": result["counts"], "production_writes": 0,
    }, sort_keys=True))

if __name__ == "__main__":
    main()
