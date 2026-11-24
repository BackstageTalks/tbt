#!/usr/bin/env python3
"""Reviewed removal of legacy ``hist-js`` rows that duplicate a native match.

A ``hist-js`` row is a duplicate only when a native (non ``hist-js``) row in
the same UTC year has the SAME ISO week, the SAME unordered pair of player IDs
and the SAME winner. Before removal, every approved stat field the duplicate
has and the native twin lacks is copied (orientation-corrected, NULL-only)
to the native row, so no statistic is lost. Nothing else changes.

Modes: stage (read-only plan), write (local partitions), verify (before/after).
Lock, backup, CAS publish and remote readback belong to the CI workflow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from import_offline_linked_serve_return import ALLOWED
from tbt.data.history_snapshot import load_manifest, load_snapshot, partition_path, update_year_manifest

POLICY = "hist_js_exact_duplicate_removal_v1"
COLS = ["match_id", "scheduled_at", "player1_id", "player2_id", "winner_id", "stats_json"]


def _years(directory):
    return sorted(int(y) for y in load_manifest(directory)["years"])


def _stats(raw):
    try:
        value = json.loads(raw) if isinstance(raw, str) and raw else {}
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _swap(stats):
    out = {}
    for k, v in stats.items():
        out[("p2_" + k[3:]) if k.startswith("p1_") else ("p1_" + k[3:]) if k.startswith("p2_") else k] = v
    return out


def _valid(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def plan_year(frame: pd.DataFrame, year: int):
    f = frame[COLS].copy()
    f["match_id"] = f["match_id"].astype(str)
    when = pd.to_datetime(f["scheduled_at"], utc=True)
    iso = when.dt.isocalendar()
    f["key"] = [(int(a), int(b), frozenset((str(c), str(d))), str(w))
                for a, b, c, d, w in zip(iso.year, iso.week, f.player1_id, f.player2_id, f.winner_id)]
    is_js = f["match_id"].str.startswith("hist-js")
    native = f[~is_js & f["winner_id"].notna()]
    # A key shared by two native rows is ambiguous: never use it.
    counts = native["key"].value_counts()
    native = native[native["key"].map(counts) == 1]
    twin = dict(zip(native["key"], native.index))
    rows, c = [], {"hist_js_rows": int(is_js.sum()), "ambiguous_native_keys": int((counts > 1).sum()),
                   "invalid_stats_json": 0}
    used_keep = set()
    for idx, r in f[is_js & f["winner_id"].notna()].iterrows():
        k = r["key"]
        if k not in twin:
            continue
        keep_idx = twin[k]
        keep = f.loc[keep_idx]
        if keep["match_id"] in used_keep:
            continue  # two hist-js rows for one native: leave both, ambiguous
        dup_stats, keep_stats = _stats(r["stats_json"]), _stats(keep["stats_json"])
        if dup_stats is None or keep_stats is None:
            c["invalid_stats_json"] += 1
            continue
        if str(r["player1_id"]) != str(keep["player1_id"]):
            dup_stats = _swap(dup_stats)
        adds = {k2: float(v) for k2, v in sorted(dup_stats.items())
                if k2 in ALLOWED and _valid(v) and keep_stats.get(k2) is None}
        used_keep.add(keep["match_id"])
        rows.append({"schema": 1, "policy": POLICY, "utc_year": year,
                     "remove_id": r["match_id"], "keep_id": keep["match_id"],
                     "stat_additions": adds})
    return rows, c


def stage(directory):
    out, totals = [], {}
    for y in _years(directory):
        frame = pd.read_parquet(partition_path(directory, y), columns=COLS)
        rows, c = plan_year(frame, y)
        out.extend(rows)
        for k, v in c.items():
            totals[k] = totals.get(k, 0) + v
    totals["removed_matches"] = len(out)
    totals["moved_stat_values"] = sum(len(r["stat_additions"]) for r in out)
    return out, totals


def write(directory, rows):
    years = sorted({int(r["utc_year"]) for r in rows})
    for y in years:
        batch = [r for r in rows if int(r["utc_year"]) == y]
        remove = {r["remove_id"] for r in batch}
        adds = {r["keep_id"]: r["stat_additions"] for r in batch}
        path = partition_path(directory, y)
        frame = pd.read_parquet(path, engine="pyarrow")
        ids = frame["match_id"].astype(str)
        if ids.duplicated().any() or not remove.issubset(set(ids)) or not set(adds).issubset(set(ids)):
            raise SystemExit(f"Planned identity missing or duplicated in {y}")
        if remove & set(adds):
            raise SystemExit("A row cannot be both removed and kept")
        before = frame.copy(deep=True)
        pos = dict(zip(ids, frame.index))
        for mid, add in adds.items():
            if not add:
                continue
            parsed = _stats(frame.at[pos[mid], "stats_json"])
            if parsed is None or any(parsed.get(k) is not None for k in add):
                raise SystemExit("Refusing stat overwrite on keep row " + mid)
            parsed.update(add)
            frame.at[pos[mid], "stats_json"] = json.dumps(parsed, sort_keys=True)
        frame = frame[~ids.isin(remove)].reset_index(drop=True)
        kept_before = before[~before["match_id"].astype(str).isin(remove)].reset_index(drop=True)
        pd.testing.assert_frame_equal(frame.drop(columns=["stats_json"]),
                                      kept_before.drop(columns=["stats_json"]), check_dtype=True)
        changed = frame["stats_json"] != kept_before["stats_json"]
        if not set(frame.loc[changed, "match_id"].astype(str)).issubset({m for m, a in adds.items() if a}):
            raise ValueError("Unplanned stats_json change")
        if len(frame) != len(before) - len(remove):
            raise ValueError("Row delta mismatch")
        tmp = path.with_name(path.name + ".dedupe.tmp")
        try:
            frame.to_parquet(tmp, engine="pyarrow", compression="zstd", index=False)
            if len(load_snapshot(tmp)) != len(frame):
                raise ValueError("Candidate partition unreadable")
            digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
            size = tmp.stat().st_size
            tmp.replace(path)
            update_year_manifest(directory, y, {"sha256": digest, "bytes": size, "rows": len(frame)})
        finally:
            if tmp.exists():
                tmp.unlink()
    return years


def verify(before_dir, after_dir, rows):
    by_year = {}
    for r in rows:
        by_year.setdefault(int(r["utc_year"]), []).append(r)
    res = {"status": "verified", "removed_matches": 0, "moved_stat_values": 0,
           "unplanned_changes": 0, "canonical_matches_after": 0}
    for y in _years(before_dir):
        a = pd.read_parquet(partition_path(before_dir, y))
        b = pd.read_parquet(partition_path(after_dir, y))
        plan = by_year.get(y, [])
        remove = {r["remove_id"] for r in plan}
        adds = {r["keep_id"]: r["stat_additions"] for r in plan}
        a_ids = a["match_id"].astype(str)
        if list(b["match_id"].astype(str)) != [m for m in a_ids if m not in remove]:
            raise ValueError(f"Identity/order mismatch after removal {y}")
        a_kept = a[~a_ids.isin(remove)].reset_index(drop=True)
        pd.testing.assert_frame_equal(a_kept.drop(columns=["stats_json"]), b.drop(columns=["stats_json"]))
        for mid, sa, sb in zip(b["match_id"].astype(str), a_kept["stats_json"], b["stats_json"]):
            if sa == sb:
                if adds.get(mid):
                    raise ValueError("Planned stats missing: " + mid)
                continue
            old, new = _stats(sa) or {}, _stats(sb) or {}
            expect = {**old, **adds.get(mid, {})}
            if not adds.get(mid) or new != expect or any(old.get(k) is not None for k in adds[mid]):
                res["unplanned_changes"] += 1
                raise ValueError("Unplanned stats change: " + mid)
            res["moved_stat_values"] += len(adds[mid])
        res["removed_matches"] += len(remove)
        res["canonical_matches_after"] += len(b)
    if res["removed_matches"] != len(rows):
        raise ValueError("Readback did not cover every planned removal")
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("stage", "write", "verify"), required=True)
    p.add_argument("--history-dir", type=Path, required=True)
    p.add_argument("--stage-file", type=Path)
    p.add_argument("--before-dir", type=Path)
    p.add_argument("--out-dir", type=Path, required=True)
    a = p.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    if a.mode == "stage":
        rows, counts = stage(a.history_dir)
        with (a.out_dir / "stage.jsonl").open("w") as fp:
            for r in rows:
                fp.write(json.dumps(r, sort_keys=True) + "\n")
        report = {"schema": 1, "mode": "stage", "policy": POLICY, "counts": counts,
                  "changed_years": sorted({r["utc_year"] for r in rows}),
                  "removals_by_year": {str(y): sum(1 for r in rows if r["utc_year"] == y)
                                       for y in sorted({r["utc_year"] for r in rows})},
                  "production_mutated": False, "provider_requests": 0}
    else:
        rows = [json.loads(x) for x in a.stage_file.read_text().splitlines() if x.strip()]
        if a.mode == "write":
            years = write(a.history_dir, rows)
            report = {"schema": 1, "mode": "write", "changed_years": years, "removed": len(rows),
                      "production_mutated": False, "provider_requests": 0}
        else:
            report = verify(a.before_dir, a.history_dir, rows)
    (a.out_dir / "report.json").write_text(json.dumps(report, sort_keys=True, indent=1))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
