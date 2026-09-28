"""Offline, fail-closed importer for private serve/return staging.

Usage: PYTHONPATH=api:scripts python scripts/import_private_serve_return.py
  --stage blinq_serve_return_import_stage.zip --history-dir .cache/tbt/history
  --out-dir .cache/tbt/serve-return-import [--write-partitions]

The source history must be downloaded from the trusted private release first.
Never upload raw provider JSON to the application repository.
"""
from __future__ import annotations
import argparse
import json
import zipfile
from collections import Counter
from pathlib import Path
from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions, write_year_partition
from tbt.data.history_safety import sanitize_history_identities
from tbt.models.feature_builder import FeatureBuilder

FIELDS = {
    "aces", "double_faults", "first_serve_win", "second_serve_win",
    "service_points_won", "return_points_won",
}
def _provider_event_id(match):
    p = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    for key in ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId"):
        if p.get(key) not in (None, ""):
            return str(p[key])
    ident = p.get("_tbt_event_identity")
    if isinstance(ident, dict) and ident.get("event_id") not in (None, ""):
        return str(ident["event_id"])
    return None

def _side_id(payload, side):
    for key in (side + "Team", side + "_team"):
        obj = payload.get(key)
        if isinstance(obj, dict) and obj.get("id") not in (None, ""):
            return str(obj["id"])
    identity = payload.get("_tbt_event_identity")
    if isinstance(identity, dict):
        obj = identity.get(side)
        if isinstance(obj, dict) and obj.get("id") not in (None, ""):
            return str(obj["id"])
    return None

def _orientation(match):
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    home, away = _side_id(payload, "home"), _side_id(payload, "away")
    p1, p2 = str(match.player1_id), str(match.player2_id)
    if not home or not away or home == away:
        return None
    if (home, away) == (p1, p2):
        return {"home": "p1", "away": "p2"}
    if (home, away) == (p2, p1):
        return {"home": "p2", "away": "p1"}
    return None

def _read_stage(path):
    with zipfile.ZipFile(path) as archive:
        rows = archive.read("staged_serve_return.jsonl").decode("utf-8").splitlines()
        manifest = json.loads(archive.read("manifest.json"))
    if manifest.get("schema_version") != 2:
        raise ValueError("Unsupported staging schema")
    return [json.loads(line) for line in rows if line.strip()]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--write-partitions", action="store_true")
    args = ap.parse_args()
    output = Path(args.out_dir)
    output.mkdir(parents=True, exist_ok=True)
    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety["quarantined_rows"]:
        raise ValueError("Historical identities ambiguous; refusing import")
    by_id = {str(m.match_id): m for m in matches}
    event_ids = Counter(_provider_event_id(m) for m in matches if _provider_event_id(m))
    rows = _read_stage(args.stage)
    seen = set()
    counts = Counter()
    review = []
    changed_years = set()
    for row in rows:
        mid = str(row.get("match_id", ""))
        eid = str(row.get("provider_event_id", ""))
        if mid in seen:
            raise ValueError("Duplicate stage match ID")
        seen.add(mid)
        match = by_id.get(mid)
        if not match or not eid or _provider_event_id(match) != eid or event_ids[eid] != 1:
            counts["identity_unmatched"] += 1
            review.append({"match_id": mid, "event_id": eid, "reason": "identity_unmatched"})
            continue
        if row.get("orientation") != "UNVERIFIED" or row.get("import_ready") is not False:
            raise ValueError("Unexpected staging trust marker")
        orientation = _orientation(match)
        if orientation is None:
            counts["orientation_unverified"] += 1
            review.append({"match_id": mid, "event_id": eid, "reason": "orientation_unverified"})
            continue
        incoming = {}
        for key, value in (row.get("home_away_stats") or {}).items():
            side, _, field = key.partition("_")
            if side not in orientation or field not in FIELDS or value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (float, int)):
                raise ValueError("Non-numeric staged statistic")
            if field not in ("aces", "double_faults") and not 0 <= value <= 1:
                raise ValueError("Out-of-range rate")
            if field in ("aces", "double_faults") and (value < 0 or int(value) != value):
                raise ValueError("Invalid count")
            canonical = orientation[side] + "_" + field
            if canonical in incoming:
                raise ValueError("Duplicate canonical statistic")
            incoming[canonical] = float(value)
        if not incoming:
            counts["no_supported_stats"] += 1
            continue
        existing = match.stats or {}
        conflicts = [key for key, value in incoming.items()
                     if existing.get(key) is not None and abs(float(existing[key]) - value) > 0.000001]
        if conflicts:
            counts["stat_conflicts"] += 1
            review.append({"match_id": mid, "event_id": eid, "reason": "stat_conflicts", "keys": conflicts})
            continue
        new_stats = dict(existing)
        new_stats.update({key: value for key, value in incoming.items() if new_stats.get(key) is None})
        if new_stats == existing:
            counts["already_present"] += 1
            continue
        match.stats = new_stats
        counts["updated"] += 1
        changed_years.add(match.scheduled_at.year)
        counts["both_players_quality_ready"] += int(
            all(FeatureBuilder._extract_quality(new_stats, prefix)[0] is not None and
                FeatureBuilder._extract_quality(new_stats, prefix)[1] is not None
                for prefix in ("p1", "p2")))
    report = {"schema": 1, "stage_rows": len(rows), "counts": dict(counts),
              "changed_years": sorted(changed_years),
              "production_mutated": False,
              "local_partitions_written": bool(args.write_partitions and changed_years),
              "note": "No private release upload or production mutation; review quarantined rows."}
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (output / "review.jsonl").open("w", encoding="utf-8") as f:
        for row in review:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if args.write_partitions:
        for year in sorted(changed_years):
            write_year_partition(matches, output / "history", year,
                                 extra_manifest={"coverage_status": "private_serve_return_import_pending_review"})
    print(json.dumps(report, indent=2))
if __name__ == "__main__":
    main()
