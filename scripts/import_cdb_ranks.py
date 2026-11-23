#!/usr/bin/env python3
"""NULL-only import of point-in-time ATP/WTA ranks (Sackmann weekly lists,
players bridged to CDB ids through linked matches) into player1_rank /
player2_rank. Only NULL cells are filled; nothing is overwritten. Local only;
lock, backup, CAS and remote readback belong to CI.
"""
from __future__ import annotations
import argparse, gzip, hashlib, json
from pathlib import Path
import pandas as pd
from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import (load_manifest, load_snapshot, partition_path,
                                       update_year_manifest)

POLICY = "sackmann_point_in_time_rank_null_only_v1"
COLS = ("player1_rank", "player2_rank")


def _read(p):
    op = gzip.open if str(p).endswith(".gz") else open
    with op(p, "rt") as fp:
        return [json.loads(x) for x in fp if x.strip()]


def _years(d):
    return sorted(int(y) for y in load_manifest(d)["years"])


def stage(directory, rows):
    want = {}
    for r in rows:
        want.setdefault(int(r["utc_year"]), {})[str(r["match_id"])] = r["ranks"]
    out, c = [], {"input": len(rows), "missing_match": 0, "already_set": 0, "invalid": 0}
    for y, ids in sorted(want.items()):
        f = pd.read_parquet(partition_path(directory, y), columns=["match_id", *COLS])
        f = f[f.match_id.astype(str).isin(ids)]
        c["missing_match"] += len(ids) - len(f)
        for mid, r1, r2 in zip(f.match_id.astype(str), f.player1_rank, f.player2_rank):
            cur = {"player1_rank": r1, "player2_rank": r2}
            adds = {}
            for k, v in ids[mid].items():
                if k not in COLS or not isinstance(v, int) or not 1 <= v <= 5000:
                    c["invalid"] += 1
                    continue
                if pd.isna(cur[k]):
                    adds[k] = v
                else:
                    c["already_set"] += 1
            if adds:
                out.append({"schema": 1, "policy": POLICY, "match_id": mid,
                            "utc_year": y, "additions": adds})
    c["staged_matches"] = len(out)
    c["new_stat_values"] = sum(len(r["additions"]) for r in out)
    return out, c


def write(directory, rows):
    years = sorted({int(r["utc_year"]) for r in rows})
    for y in years:
        batch = {r["match_id"]: r["additions"] for r in rows if int(r["utc_year"]) == y}
        path = partition_path(directory, y)
        frame = pd.read_parquet(path, engine="pyarrow")
        ids = frame.match_id.astype(str)
        if ids.duplicated().any():
            raise ValueError("Duplicate match_id")
        before = frame.copy(deep=True)
        pos = {mid: i for i, mid in zip(frame.index, ids)}
        for mid, add in batch.items():
            if mid not in pos:
                raise SystemExit(f"Staged row missing in {y}: {mid}")
            for k, v in add.items():
                if not pd.isna(frame.at[pos[mid], k]):
                    raise SystemExit("Refusing rank overwrite: " + mid)
                frame.at[pos[mid], k] = v
        pd.testing.assert_frame_equal(frame.drop(columns=list(COLS)),
                                      before.drop(columns=list(COLS)), check_dtype=True)
        for col in COLS:
            old, new = before[col], frame[col]
            same = (old == new) | (old.isna() & new.isna())
            if ((~same) & (~ids.isin(batch))).any() or old[~same].notna().any():
                raise ValueError("Unstaged or overwritten rank cell")
        meta = load_manifest(directory).get("years", {}).get(str(y))
        if not isinstance(meta, dict) or int(meta.get("rows", -1)) != len(frame):
            raise ValueError("Manifest row count mismatch")
        tmp = path.with_name(path.name + ".rank.tmp")
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
    by = {r["match_id"]: r["additions"] for r in rows}
    res = {"status": "verified", "canonical_matches": 0, "enriched_matches": 0,
           "new_stat_values": 0, "existing_values_overwritten": 0, "unverified_identities": 0}
    for y in _years(before_dir):
        a = pd.read_parquet(partition_path(before_dir, y))
        b = pd.read_parquet(partition_path(after_dir, y))
        if list(a.match_id.astype(str)) != list(b.match_id.astype(str)):
            raise ValueError(f"Identity/order changed {y}")
        pd.testing.assert_frame_equal(a.drop(columns=list(COLS)), b.drop(columns=list(COLS)))
        for mid, a1, a2, b1, b2 in zip(a.match_id.astype(str), a.player1_rank, a.player2_rank,
                                        b.player1_rank, b.player2_rank):
            add = by.get(mid, {})
            for k, x, z in (("player1_rank", a1, b1), ("player2_rank", a2, b2)):
                if k in add:
                    if not pd.isna(x) or pd.isna(z) or int(z) != add[k]:
                        raise ValueError("Rank readback mismatch: " + mid)
                    res["new_stat_values"] += 1
                elif not ((pd.isna(x) and pd.isna(z)) or x == z):
                    raise ValueError("Unstaged rank changed: " + mid)
            if add:
                res["enriched_matches"] += 1
        res["canonical_matches"] += len(a)
    if res["enriched_matches"] != len(rows):
        raise ValueError("Readback did not cover every staged row")
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("stage", "write", "verify"), required=True)
    p.add_argument("--history-dir", type=Path, required=True)
    p.add_argument("--input", type=Path)
    p.add_argument("--stage-file", type=Path)
    p.add_argument("--before-dir", type=Path)
    p.add_argument("--out-dir", type=Path, required=True)
    a = p.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    if a.mode == "stage":
        rows, counts = stage(a.history_dir, _read(a.input))
        with (a.out_dir / "stage.jsonl").open("w") as fp:
            for r in rows:
                fp.write(json.dumps(r, sort_keys=True) + "\n")
        res = {"schema": 1, "mode": "stage", "counts": counts,
               "changed_years": sorted({r["utc_year"] for r in rows}),
               "production_mutated": False, "provider_requests": 0}
    elif a.mode == "write":
        rows = _read(a.stage_file)
        years = write(a.history_dir, rows)
        res = {"schema": 1, "mode": "write", "updated": len(rows), "changed_years": years,
               "new_stat_values": sum(len(r["additions"]) for r in rows),
               "production_mutated": False, "provider_requests": 0}
    else:
        res = verify(a.before_dir, a.history_dir, _read(a.stage_file))
    (a.out_dir / "report.json").write_text(json.dumps(res, sort_keys=True, indent=2) + "\n")
    print(json.dumps(res, sort_keys=True))


if __name__ == "__main__":
    main()
