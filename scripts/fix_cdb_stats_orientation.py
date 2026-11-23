#!/usr/bin/env python3
"""Swap p1_*/p2_* statistics for CDB rows whose orientation an independent
source (Sackmann winner/loser stats) proves reversed.

Only stats_json of the listed rows changes, and only by exchanging the p1_ and
p2_ prefixes (no value is created or lost). Every other cell and row must be
identical. Local only; lock, backup, CAS and remote readback belong to CI.
"""
from __future__ import annotations
import argparse, gzip, hashlib, json
from pathlib import Path
import pandas as pd
from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import (load_manifest, load_snapshot, partition_path,
                                       update_year_manifest)

POLICY = "source_confirmed_p1_p2_swap_v1"


def swapped(stats: dict) -> dict:
    out = {}
    for k, v in stats.items():
        if k.startswith("p1_"):
            out["p2_" + k[3:]] = v
        elif k.startswith("p2_"):
            out["p1_" + k[3:]] = v
        else:
            out[k] = v
    if len(out) != len(stats):
        raise ValueError("Swap collision")
    return dict(sorted(out.items()))


def _h(v) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read(p: Path):
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, "rt") as fp:
        return [json.loads(x) for x in fp if x.strip()]


def _frame(directory, year):
    return pd.read_parquet(partition_path(directory, year), engine="pyarrow")


def stage(directory, rows):
    by_year = {}
    for r in rows:
        by_year.setdefault(int(r["utc_year"]), set()).add(str(r["match_id"]))
    out, c = [], {"input": len(rows), "missing_match": 0, "no_stats": 0, "already_consistent": 0}
    for y, ids in sorted(by_year.items()):
        f = _frame(directory, y)
        f = f[f.match_id.astype(str).isin(ids)]
        c["missing_match"] += len(ids) - len(f)
        for mid, raw, p1, w in zip(f.match_id.astype(str), f.stats_json, f.player1_id, f.winner_id):
            st = json.loads(raw) if isinstance(raw, str) else {}
            if "p1_service_points_won" not in st or "p1_return_points_won" not in st:
                c["no_stats"] += 1
                continue
            # Idempotence: only rows still contradicting the canonical winner.
            edge = st["p1_service_points_won"] + st["p1_return_points_won"] - 1
            if (edge > 0) == (str(w) == str(p1)):
                c["already_consistent"] += 1
                continue
            out.append({"schema": 1, "policy": POLICY, "match_id": mid, "utc_year": y,
                        "before_hash": _h(st), "after_hash": _h(swapped(st))})
    c["staged_matches"] = len(out)
    c["new_stat_values"] = 0
    return out, c


def write(directory, rows):
    years = sorted({int(r["utc_year"]) for r in rows})
    for y in years:
        batch = {r["match_id"]: r for r in rows if int(r["utc_year"]) == y}
        path = partition_path(directory, y)
        frame = _frame(directory, y)
        ids = frame.match_id.astype(str)
        if ids.duplicated().any():
            raise ValueError("Duplicate match_id in partition")
        others = frame.drop(columns=["stats_json"]).copy(deep=True)
        orig = frame["stats_json"].copy(deep=True)
        hit = 0
        for i, mid in zip(frame.index, ids):
            r = batch.get(mid)
            if r is None:
                continue
            st = json.loads(frame.at[i, "stats_json"])
            if _h(st) != r["before_hash"]:
                raise SystemExit("Row changed since stage: " + mid)
            new = swapped(st)
            if _h(new) != r["after_hash"]:
                raise SystemExit("Swap not reproducible: " + mid)
            frame.at[i, "stats_json"] = json.dumps(new, ensure_ascii=False, sort_keys=True,
                                                   separators=(",", ":"), allow_nan=False)
            hit += 1
        if hit != len(batch):
            raise SystemExit(f"Staged rows missing in {y}")
        pd.testing.assert_frame_equal(frame.drop(columns=["stats_json"]), others, check_dtype=True)
        untouched = ~ids.isin(batch)
        if not frame.loc[untouched, "stats_json"].equals(orig.loc[untouched]):
            raise ValueError("Unstaged stats cell changed")
        meta = load_manifest(directory).get("years", {}).get(str(y))
        if not isinstance(meta, dict) or int(meta.get("rows", -1)) != len(frame):
            raise ValueError("Manifest row count mismatch")
        tmp = path.with_name(path.name + ".swap.tmp")
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
    res = {"status": "verified", "canonical_matches": 0, "enriched_matches": 0,
           "new_stat_values": 0, "existing_values_overwritten": 0,
           "swapped_matches": 0, "unverified_identities": 0}
    by = {r["match_id"]: r for r in rows}
    for y in sorted(int(k) for k in load_manifest(before_dir)["years"]):
        a, b = _frame(before_dir, y), _frame(after_dir, y)
        if list(a.match_id.astype(str)) != list(b.match_id.astype(str)):
            raise ValueError(f"Identity/order changed in {y}")
        pd.testing.assert_frame_equal(a.drop(columns=["stats_json"]), b.drop(columns=["stats_json"]))
        for mid, x, z in zip(a.match_id.astype(str), a.stats_json, b.stats_json):
            r = by.get(mid)
            if r is None:
                if not (x == z or (pd.isna(x) and pd.isna(z))):
                    raise ValueError("Unstaged stats changed: " + mid)
                continue
            if _h(json.loads(x)) != r["before_hash"] or _h(json.loads(z)) != r["after_hash"]:
                raise ValueError("Swap readback mismatch: " + mid)
            res["swapped_matches"] += 1
        res["canonical_matches"] += len(a)
    res["enriched_matches"] = res["swapped_matches"]
    if res["swapped_matches"] != len(rows):
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
               "new_stat_values": 0, "production_mutated": False, "provider_requests": 0}
    else:
        res = verify(a.before_dir, a.history_dir, _read(a.stage_file))
    (a.out_dir / "report.json").write_text(json.dumps(res, sort_keys=True, indent=2) + "\n")
    print(json.dumps(res, sort_keys=True))


if __name__ == "__main__":
    main()
