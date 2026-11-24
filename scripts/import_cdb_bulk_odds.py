#!/usr/bin/env python3
"""NULL-only import of already-paid tennisapi1 daily bulk odds (bet365 Home/Away)
into canonical CDB provider_context_json["_tbt_market_history"].

Join is exact: bulk event id == CDB _tbt_provider_event_id / _tbt_event_identity.
Orientation: provider home == CDB player1 (from _tbt_event_identity); if the
bulk 'winning' flag contradicts the CDB winner the row is skipped. Only rows
WITHOUT an existing _tbt_market_history are touched; nothing is overwritten.
Local only; lock, backup, CAS and remote readback belong to CI.
"""
from __future__ import annotations
import argparse, glob, gzip, hashlib, json
from fractions import Fraction
from pathlib import Path
import pandas as pd
from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import (load_manifest, load_snapshot, partition_path,
                                       update_year_manifest)

POLICY = "tennisapi1_bulk_odds_market_history_null_only_v1"
KEY = "_tbt_market_history"


def dec(frac):
    try:
        v = 1.0 + float(Fraction(str(frac)))
    except (ValueError, ZeroDivisionError):
        return None
    return round(v, 4) if 1.0 < v < 1000 else None


def side(p1, p2):
    if p1 is None or p2 is None:
        return None
    i1, i2 = 1 / p1, 1 / p2
    s = i1 + i2
    return {"player1_implied_probability": i1 / s, "player1_odds": p1,
            "player2_implied_probability": i2 / s, "player2_odds": p2,
            "raw_overround": s - 1}


def load_bulk(directory):
    out = {}
    for f in sorted(glob.glob(f"{directory}/**/*.json.gz", recursive=True)):
        with gzip.open(f, "rt") as fp:
            odds = (json.load(fp) or {}).get("odds") or {}
        for eid, m in odds.items():
            if not isinstance(m, dict) or m.get("marketId") != 1 or m.get("isLive"):
                continue
            ch = {c.get("name"): c for c in m.get("choices") or [] if isinstance(c, dict)}
            if set(ch) != {"1", "2"}:
                continue
            out[str(eid)] = (ch["1"], ch["2"], Path(f).name[:10])
    return out


def _h(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _years(d):
    return sorted(int(y) for y in load_manifest(d)["years"])


def build(pc_raw, p1, w, bulk):
    pc = json.loads(pc_raw) if isinstance(pc_raw, str) and pc_raw else {}
    if not isinstance(pc, dict) or KEY in pc:
        return None, "has_market_history"
    ident = pc.get("_tbt_event_identity") or {}
    eid = str(pc.get("_tbt_provider_event_id") or ident.get("event_id") or "")
    if eid not in bulk:
        return None, "no_bulk"
    if str(ident.get("event_id") or eid) != eid or not ident.get("home"):
        return None, "no_identity"
    home_p1 = str(ident["home"]) == str(p1)
    a, b, day = bulk[eid]
    c1, c2 = (a, b) if home_p1 else (b, a)
    if w is not None and str(w) != "" and (c1.get("winning") or c2.get("winning")):
        if bool(c1.get("winning")) != (str(w) == str(p1)):
            return None, "winner_conflict"
    opening = side(dec(c1.get("initialFractionalValue")), dec(c2.get("initialFractionalValue")))
    closing = side(dec(c1.get("fractionalValue")), dec(c2.get("fractionalValue")))
    if not opening or not closing:
        return None, "bad_price"
    value = {"schema": 1, "status": "linked", "price_kind": "historical_open_close",
             "source": "tennisapi1_bulk_daily:bet365", "source_match_id": eid,
             "source_file": day, "opening": opening, "closing": closing,
             "closing_semantics": "last_recorded_before_match",
             "model_feature_policy": "opening_only_candidate; closing_validation_only"}
    new = dict(pc)
    new[KEY] = value
    return (pc, new), "staged"


def stage(directory, bulk):
    out, c = [], {}
    for y in _years(directory):
        f = pd.read_parquet(partition_path(directory, y),
                            columns=["match_id", "provider_context_json", "player1_id", "winner_id"])
        for mid, pc, p1, w in zip(f.match_id.astype(str), f.provider_context_json, f.player1_id, f.winner_id):
            res, why = build(pc, p1, w, bulk)
            c[why] = c.get(why, 0) + 1
            if res:
                old, new = res
                out.append({"schema": 1, "policy": POLICY, "match_id": mid, "utc_year": y,
                            "before_hash": _h(old), "value": new[KEY]})
    c["staged_matches"] = len(out)
    c["new_stat_values"] = 0
    c.pop("no_bulk", None)
    return out, c


def _apply(pc_raw, row):
    pc = json.loads(pc_raw) if isinstance(pc_raw, str) and pc_raw else {}
    if _h(pc) != row["before_hash"] or KEY in pc:
        raise SystemExit("Row changed since stage: " + row["match_id"])
    pc[KEY] = row["value"]
    return json.dumps(pc, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def write(directory, rows):
    years = sorted({int(r["utc_year"]) for r in rows})
    for y in years:
        batch = {r["match_id"]: r for r in rows if int(r["utc_year"]) == y}
        path = partition_path(directory, y)
        frame = pd.read_parquet(path, engine="pyarrow")
        ids = frame.match_id.astype(str)
        if ids.duplicated().any():
            raise ValueError("Duplicate match_id")
        others = frame.drop(columns=["provider_context_json"]).copy(deep=True)
        orig = frame["provider_context_json"].copy(deep=True)
        hit = 0
        for i, mid in zip(frame.index, ids):
            r = batch.get(mid)
            if r is not None:
                frame.at[i, "provider_context_json"] = _apply(frame.at[i, "provider_context_json"], r)
                hit += 1
        if hit != len(batch):
            raise SystemExit(f"Staged rows missing in {y}")
        pd.testing.assert_frame_equal(frame.drop(columns=["provider_context_json"]), others, check_dtype=True)
        untouched = ~ids.isin(batch)
        if not frame.loc[untouched, "provider_context_json"].equals(orig.loc[untouched]):
            raise ValueError("Unstaged provider context changed")
        meta = load_manifest(directory).get("years", {}).get(str(y))
        if not isinstance(meta, dict) or int(meta.get("rows", -1)) != len(frame):
            raise ValueError("Manifest row count mismatch")
        tmp = path.with_name(path.name + ".odds.tmp")
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
    by = {r["match_id"]: r for r in rows}
    res = {"status": "verified", "canonical_matches": 0, "enriched_matches": 0, "new_stat_values": 0,
           "existing_values_overwritten": 0, "unverified_identities": 0}
    for y in _years(before_dir):
        a = pd.read_parquet(partition_path(before_dir, y))
        b = pd.read_parquet(partition_path(after_dir, y))
        if list(a.match_id.astype(str)) != list(b.match_id.astype(str)):
            raise ValueError(f"Identity/order changed {y}")
        pd.testing.assert_frame_equal(a.drop(columns=["provider_context_json"]),
                                      b.drop(columns=["provider_context_json"]))
        for mid, x, z in zip(a.match_id.astype(str), a.provider_context_json, b.provider_context_json):
            r = by.get(mid)
            if r is None:
                if not (x == z or (pd.isna(x) and pd.isna(z))):
                    raise ValueError("Unstaged context changed: " + mid)
                continue
            if _apply(x, r) != z:
                raise ValueError("Readback mismatch: " + mid)
            res["enriched_matches"] += 1
        res["canonical_matches"] += len(a)
    if res["enriched_matches"] != len(rows):
        raise ValueError("Readback did not cover every staged row")
    return res


def _read(p):
    op = gzip.open if str(p).endswith(".gz") else open
    with op(p, "rt") as fp:
        return [json.loads(x) for x in fp if x.strip()]


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
        rows, counts = stage(a.history_dir, load_bulk(a.input))
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
