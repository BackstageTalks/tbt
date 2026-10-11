"""Wimbledon 2024: checksum-pinned add-only CDB stage from supplied raw match/point CSV.

No network, CDB writes or model actions. Conflicting matches and identities stay
quarantined. Source rights/approval are managed outside this technical adapter.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from _bootstrap import ROOT  # noqa: F401
from tbt.data.offline_odds import norm_text

YEAR = 2024
ZIP_SHA = "cd464e89a19a0c6440fdd2928d14e375065d2baf96ff01c3c9860077a1803c20"
MATCH_SHA = "6424486fd7eb7e21aa1a57232e7f56dc0e5f34e39c63642a89973a7a535f1299"
POINT_SHA = "974c6c7509f341ca6a1cf5a7e69e721a7c515a1449bf014219983ef303eee2cf"
FIELDS = (("Ace", "aces"), ("DoubleFault", "double_faults"),
          ("UnforcedError", "unforced_errors"), ("NetPoint", "net_points"),
          ("NetPointWon", "net_points_won"))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def checked(path, expected):
    if digest(path) != expected:
        raise ValueError("Checksum mismatch: " + str(path))


def read_csv(path, required):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not set(required).issubset(reader.fieldnames or []):
            raise ValueError("Missing original CSV columns")
        return list(reader)


def integer(value):
    if value is None or str(value).strip() == "":
        raise ValueError("Absent source count")
    try:
        n = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Non-numeric count") from error
    if not math.isfinite(n) or not n.is_integer() or n < 0 or n > 1000:
        raise ValueError("Invalid count")
    return int(n)


def bit(value):
    val = str(value).strip().lower()
    if val in ("1", "1.0", "true"):
        return 1
    if val in ("0", "0.0", "false"):
        return 0
    raise ValueError("Nonbinary point flag")


def _points(rows):
    totals = defaultdict(Counter)
    duplicates = set()
    invalid = set()
    seen = set()
    specials = 0
    for row in rows:
        sid = str(row["match_id"]).strip()
        location = str(row["PointNumberInGame"]).strip()
        if not re.fullmatch(r"[1-9]\d*", location):
            specials += 1
            continue
        key = (sid, str(row.get("SetNumber")), str(row.get("GameNumber")), location)
        if key in seen:
            duplicates.add(sid)
            continue
        seen.add(key)
        server = str(row.get("PointServerPlayer") or "").strip()
        if server not in ("1", "2"):
            invalid.add(sid)
            continue
        try:
            totals[sid]["Player%sAce" % server] += bit(row["IsAcePoint"])
            totals[sid]["Player%sDoubleFault" % server] += bit(row["IsDoubleFaultPoint"])
        except ValueError:
            invalid.add(sid)
    return totals, invalid | duplicates, specials


def classify(raw, point_rows, frame, cdb_sha):
    by_pair = defaultdict(list)
    if frame["match_id"].astype(str).duplicated().any():
        raise ValueError("Nonunique canonical match identity")
    needed = {"match_id", "tour", "scheduled_at", "tournament", "player1_id",
              "player2_id", "player1_name", "player2_name", "stats_json"}
    if not needed.issubset(frame.columns):
        raise ValueError("Bad canonical Parquet schema")
    for idx, row in frame.iterrows():
        day = pd.Timestamp(row["scheduled_at"])
        if day.tzinfo is None:
            raise ValueError("Naive CDB time")
        if day.tz_convert("UTC").year != YEAR:
            raise ValueError("Unexpected CDB year")
        if str(row["tour"]).lower() not in ("atp", "wta") or "wimbledon" not in norm_text(row["tournament"]):
            continue
        pair = tuple(sorted((norm_text(row["player1_name"]), norm_text(row["player2_name"]))))
        by_pair[pair].append((idx, row))
    events, invalid_tapes, special = _points(point_rows)
    seen_raw, seen_cdb = set(), set()
    proposals, quarantine = [], []
    metrics = Counter()
    for entry in raw:
        metrics["source_matches"] += 1
        sid = str(entry["match_id"]).strip()
        if not sid or sid in seen_raw:
            raise ValueError("Duplicate source match id")
        seen_raw.add(sid)
        try:
            if integer(entry["Year"]) != YEAR:
                raise ValueError("Wrong year")
            a, b = norm_text(entry["Player1Name"]), norm_text(entry["Player2Name"])
            if not a or not b or a == b:
                raise ValueError("Bad names")
        except ValueError:
            quarantine.append({"source_id": sid, "reason": "invalid_source_pair"})
            continue
        matches = by_pair.get(tuple(sorted((a, b))), [])
        if len(matches) != 1:
            quarantine.append({"source_id": sid, "reason": "missing_or_ambiguous_match",
                               "candidate_count": len(matches)})
            continue
        _, row = matches[0]
        mid = str(row["match_id"])
        if mid in seen_cdb:
            raise ValueError("Two source matches link one canonical ID")
        seen_cdb.add(mid)
        swapped = a == norm_text(row["player2_name"])
        if not str(row["player1_id"] or "") or not str(row["player2_id"] or ""):
            quarantine.append({"source_id": sid, "match_id": mid, "reason": "no_canonical_player_ids"})
            continue
        try:
            values = {("Player%d%s" % (side, metric)): integer(entry.get("Player%d%s" % (side, metric)))
                      for side in (1, 2) for metric, _ in FIELDS}
            if any(values["Player%dNetPointWon" % p] > values["Player%dNetPoint" % p] for p in (1, 2)):
                raise ValueError("Net points inconsistent")
            if sid in invalid_tapes or sid not in events:
                raise ValueError("Unusable original point tape")
            for side in (1, 2):
                for metric in ("Ace", "DoubleFault"):
                    if events[sid]["Player%d%s" % (side, metric)] != values["Player%d%s" % (side, metric)]:
                        raise ValueError("Point flags disagree with match total")
            old = json.loads(row["stats_json"])
            if not isinstance(old, dict):
                raise ValueError("Invalid stored stats")
        except (ValueError, TypeError, KeyError):
            quarantine.append({"source_id": sid, "match_id": mid, "reason": "point_or_match_value_inconsistent"})
            continue
        incoming = {}
        for side in (1, 2):
            target = 3 - side if swapped else side
            for suffix, canonical in FIELDS:
                incoming["p%d_%s" % (target, canonical)] = values["Player%d%s" % (side, suffix)]
        conflicting, missing, equal = [], {}, 0
        for key, val in incoming.items():
            current = old.get(key)
            if current is None:
                missing[key] = val
            else:
                try:
                    eq = not isinstance(current, bool) and math.isfinite(float(current)) and float(current) == val
                except (TypeError, ValueError, OverflowError):
                    eq = False
                if eq:
                    equal += 1
                else:
                    conflicting.append(key)
        metrics["equal_fields"] += equal
        metrics["conflicting_fields"] += len(conflicting)
        if conflicting:
            metrics["conflicting_matches"] += 1
            metrics["missing_on_conflicting_matches"] += len(missing)
            quarantine.append({"source_id": sid, "match_id": mid, "reason": "canonical_stat_conflict",
                               "fields": sorted(conflicting)})
            continue
        metrics["clean_matches"] += 1
        if not missing:
            metrics["already_complete"] += 1
            continue
        proposals.append({
            "schema": 1, "source": "wimbledon_2024_raw_match_and_point_csv",
            "source_id": sid, "match_id": mid, "year": YEAR,
            "match_sha256": MATCH_SHA, "points_sha256": POINT_SHA,
            "cdb_sha256": cdb_sha, "swapped": swapped,
            "expected_identity": {k: str(row[k]) for k in (
                "tour", "scheduled_at", "tournament", "player1_id", "player2_id",
                "player1_name", "player2_name", "match_id")},
            "additions": missing, "expected_original_null_fields": sorted(missing),
            "available_at": None, "model_eligibility": "postmatch_only",
        })
        metrics["staged_matches"] += 1
        metrics["staged_fields"] += len(missing)
    metrics["quarantined_matches"] = len(quarantine)
    metrics["special_point_rows"] = special
    metrics["unique_linked_source_matches"] = len(seen_cdb)
    return proposals, quarantine, dict(metrics)


def run(args):
    checked(args.match_csv, MATCH_SHA)
    checked(args.point_csv, POINT_SHA)
    manifest = json.loads(args.manifest.read_text())
    meta = (manifest.get("years") or {}).get(str(YEAR), {})
    cdb_sha = digest(args.cdb_year)
    if meta.get("sha256") != cdb_sha or meta.get("asset") != args.cdb_year.name:
        raise ValueError("Canonical 2024 partition disagrees with manifest")
    rel = json.loads(args.release_json.read_text())
    names = {asset["name"]: asset["digest"] for asset in rel["assets"]}
    if names.get(args.cdb_year.name) != "sha256:" + cdb_sha:
        raise ValueError("Release does not match 2024 CDB bytes")
    if names.get(args.manifest.name) != "sha256:" + digest(args.manifest):
        raise ValueError("Release does not match CDB manifest bytes")
    frame = pd.read_parquet(args.cdb_year)
    if int(meta.get("rows", -1)) != len(frame):
        raise ValueError("CDB 2024 row count changed")
    matches = read_csv(args.match_csv, {"match_id", "Year", "Player1Name", "Player2Name"} |
                       {"Player%d%s" % (p, name) for p in (1, 2) for name, _ in FIELDS})
    points = read_csv(args.point_csv, {"match_id", "PointNumberInGame", "PointServerPlayer",
                                       "SetNumber", "GameNumber", "IsAcePoint", "IsDoubleFaultPoint"})
    if len(matches) != 252 or len(points) != 48155:
        raise ValueError("Wimbledon 2024 raw source row count changed")
    proposal, quarantine, metrics = classify(matches, points, frame, cdb_sha)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("stage.jsonl", proposal), ("quarantine.jsonl", quarantine)):
        (args.out / name).write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    report = {
        "schema": 1, "status": "prepared_for_isolated_replay",
        "year": YEAR, "year_rows": len(frame), "cdb_sha256": cdb_sha,
        "source_zip_sha256": ZIP_SHA, "match_sha256": MATCH_SHA, "points_sha256": POINT_SHA,
        "counts": metrics, "write_performed": False, "model_trained": False, "provider_requests": 0,
        "stage_sha256": digest(args.out / "stage.jsonl"),
        "stage_has_conflicts": False,
    }
    (args.out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main():
    p = argparse.ArgumentParser()
    for name in ("match_csv", "point_csv", "cdb_year", "manifest", "release_json", "out"):
        p.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    print(json.dumps(run(p.parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
