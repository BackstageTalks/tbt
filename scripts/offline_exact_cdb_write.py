"""Fail-closed additive stats-only Parquet writer and full persisted readback.

Used by the audited Hwaitt 2011-2019 importer. Keep all unrelated Parquet
cells byte-equivalent at logical value level; never reserialize 900k unrelated
MatchRecord objects into a canonical release. Does NOT publish remotely.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import (
    load_manifest, load_snapshot, partition_path, update_year_manifest,
)


def _rows(matches):
    result = {}
    for match in matches:
        key = str(match.match_id)
        if not key or key in result:
            raise ValueError("Missing or duplicate canonical match identity")
        result[key] = match
    return result


def _same_except_stats(left, right):
    before = left.to_storage_dict()
    after = right.to_storage_dict()
    before.pop("stats", None)
    after.pop("stats", None)
    return before == after


def _additions(original, changed):
    if not _same_except_stats(original, changed):
        raise ValueError("Staged write attempted canonical identity or context change")
    old = dict(original.stats or {})
    new = dict(changed.stats or {})
    for key, value in old.items():
        if value is not None and (key not in new or new[key] != value):
            raise ValueError("Existing canonical statistic changed")
    from import_offline_linked_serve_return import ALLOWED
    added = {key: value for key, value in new.items() if old.get(key) is None and value is not None}
    if not added or not set(added).issubset(ALLOWED):
        raise ValueError("Missing or invalid additive source statistics")
    return added


def _verify_entire_partition(before, persisted, expected_additions):
    before_by = _rows(before)
    after_by = _rows(persisted)
    if before_by.keys() != after_by.keys():
        raise ValueError("Full-partition canonical match identities changed")
    for mid, previous in before_by.items():
        current = after_by[mid]
        if not _same_except_stats(previous, current):
            raise ValueError(f"Unstaged canonical field modified: {mid}")
        expected = dict(previous.stats or {})
        expected.update(expected_additions.get(mid, {}))
        if current.stats != expected:
            raise ValueError(f"Unstaged/missing persisted stats: {mid}")
    return len(before_by)


def write_exact_stats_partition(history_dir, year, changed_matches, changed_ids):
    """Patch exact stats_json rows for proven additions; fail before local replace."""
    directory = Path(history_dir)
    year = int(year)
    path = partition_path(directory, year)
    before = load_snapshot(path)
    before_by = _rows(before)
    after_by = _rows(m for m in changed_matches if m.scheduled_at.year == year)
    if before_by.keys() != after_by.keys():
        raise ValueError("Local import omitted or invented canonical matches")
    ids = {str(mid) for mid in changed_ids}
    if not ids or not ids.issubset(before_by):
        raise ValueError("Changed match identity missing from canonical year")
    frame = pd.read_parquet(path, engine="pyarrow")
    if "match_id" not in frame or "stats_json" not in frame:
        raise ValueError("Invalid canonical Parquet schema")
    frame_ids = frame["match_id"].astype(str)
    if frame_ids.duplicated().any() or set(frame_ids) != set(before_by):
        raise ValueError("Parquet and canonical identity disagree")
    by_index = dict(zip(frame_ids, frame.index))
    other_columns = frame.drop(columns=["stats_json"]).copy(deep=True)
    original_stat_column = frame["stats_json"].copy(deep=True)
    delta = {}
    for mid, old in before_by.items():
        updated = after_by[mid]
        if mid not in ids:
            if old.to_storage_dict() != updated.to_storage_dict():
                raise ValueError(f"Unstaged match mutated in memory: {mid}")
            continue
        additions = _additions(old, updated)
        raw = frame.at[by_index[mid], "stats_json"]
        if not isinstance(raw, str):
            raise ValueError("Missing original stats_json")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Corrupt original stats_json")
        for key, value in additions.items():
            if parsed.get(key) is not None:
                raise ValueError("Parquet field overwrite forbidden")
            parsed[key] = value
        frame.at[by_index[mid], "stats_json"] = json.dumps(
            parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        delta[mid] = additions
    pd.testing.assert_frame_equal(
        frame.drop(columns=["stats_json"]), other_columns, check_dtype=True
    )
    untouched = ~frame.index.isin({by_index[mid] for mid in ids})
    if not frame.loc[untouched, "stats_json"].equals(original_stat_column.loc[untouched]):
        raise ValueError("Unstaged physical Parquet JSON cell changed")
    original_meta = load_manifest(directory).get("years", {}).get(str(year))
    if not isinstance(original_meta, dict) or int(original_meta.get("rows", -1)) != len(frame):
        raise ValueError("CDB manifest row count or partition missing")
    temp = path.with_name(path.name + ".verified-stats.tmp")
    try:
        frame.to_parquet(temp, engine="pyarrow", compression="zstd", index=False)
        if temp.stat().st_size <= 0:
            raise ValueError("Empty candidate CDB partition")
        _verify_entire_partition(before, load_snapshot(temp), delta)
        digest = hashlib.sha256(temp.read_bytes()).hexdigest()
        size = temp.stat().st_size
        temp.replace(path)
        update_year_manifest(directory, year, {
            "sha256": digest, "bytes": size, "rows": len(frame),
        })
    finally:
        if temp.exists():
            temp.unlink()
    return {"year": year, "matches_checked": len(before), "enriched_matches": len(ids),
            "added_values": sum(map(len, delta.values())), "existing_values_overwritten": 0}


def verify_persisted(before_dir, after_dir, stage_rows, changed_years):
    """Verify ALL rows on affected years from separate prewrite and remote copies."""
    years = sorted(set(map(int, changed_years)))
    before_dir, after_dir = Path(before_dir), Path(after_dir)
    stage_map = {}
    for item in stage_rows:
        if item.get("delayed_observation") is not None:
            raise ValueError("Unapproved delayed observation in stats-only stage")
        key = str(item.get("match_id") or "")
        if not key or key in stage_map:
            raise ValueError("Duplicate/missing source staged ID")
        stage_map[key] = item
    total, enriched, added_count = 0, 0, 0
    all_changed = set()
    for year in years:
        before = load_snapshot(partition_path(before_dir, year))
        after = load_snapshot(partition_path(after_dir, year))
        by_before = _rows(before)
        by_after = _rows(after)
        if by_before.keys() != by_after.keys():
            raise ValueError("Persisted year identity mismatch")
        expected = {}
        for mid, original in by_before.items():
            current = by_after[mid]
            if original.stats == current.stats:
                # Source rows previously present or rejected for conflict
                # must remain unchanged; checked by full-partition verification.
                continue
            row = stage_map.get(mid)
            if row is None:
                raise ValueError("Persisted change without a staged source match")
            if int(original.scheduled_at.year) != year:
                raise ValueError("Staged year differs from canonical UTC year")
            if row.get("schema") != 1 or row.get("import_ready") is not True:
                raise ValueError("Nonverified staged stats row")
            from import_offline_linked_serve_return import _signature, ALLOWED
            if row.get("canonical") != _signature(original):
                raise ValueError("Original canonical source signature changed")
            incoming = row.get("incoming_stats")
            if not isinstance(incoming, dict) or not incoming or not set(incoming).issubset(ALLOWED):
                raise ValueError("Untrusted source field name")
            old = original.stats or {}
            if any(k in old and old[k] is not None and abs(float(old[k]) - float(v)) > 1e-6
                   for k, v in incoming.items()):
                raise ValueError("Conflicting source field in changed match")
            additions = {k: float(v) for k, v in incoming.items() if old.get(k) is None}
            if not additions:
                raise ValueError("Changed match lacks verified source additions")
            expected[mid] = additions
            all_changed.add(mid)
            added_count += len(additions)
        total += _verify_entire_partition(before, after, expected)
        enriched += len(expected)
    if set(all_changed) - set(stage_map):
        raise ValueError("Persisted changes beyond staged identities")
    return {"status": "verified", "canonical_rows_checked": total,
            "changed_years": years, "enriched_matches": enriched,
            "added_values": added_count, "existing_values_overwritten": 0,
            "unverified_identities": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-dir", type=Path, required=True)
    parser.add_argument("--after-dir", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--changed-years", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage = [json.loads(x) for x in args.stage.read_text().splitlines() if x.strip()]
    result = verify_persisted(args.before_dir, args.after_dir, stage, json.loads(args.changed_years))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
