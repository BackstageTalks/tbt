#!/usr/bin/env python3
"""NULL-only import of pre-staged match statistics (JSONL.gz) into canonical CDB.

Each input row: {"match_id", "stats": {...}}. Only ALLOWED stat fields that are
currently NULL in the CDB row are added; nothing existing is ever overwritten,
no identity/context column changes. Local only; publication, immutable backup,
manifest CAS, global writer lock and remote readback belong to CI.
"""
from __future__ import annotations
import argparse, gzip, json, math
from pathlib import Path
from _bootstrap import ROOT  # noqa: F401
from import_offline_linked_serve_return import ALLOWED
from recover_cdb_opponent_service_rates import _load, _sha, _storage, verify_readback
from offline_exact_cdb_write import write_exact_stats_partition

POLICY = "staged_stats_null_only_v1"


def _read(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fp:
        return [json.loads(x) for x in fp if x.strip()]


def stage(matches, rows):
    by_id = {str(m.match_id): m for m in matches}
    out, c = [], {"input": len(rows), "missing_match": 0, "nothing_new": 0, "invalid": 0}
    seen = set()
    for r in rows:
        mid = str(r.get("match_id") or "")
        m = by_id.get(mid)
        if m is None or mid in seen:
            c["missing_match"] += 1
            continue
        old = dict(m.stats or {})
        new = r.get("stats") or {}
        if any(k not in ALLOWED or not isinstance(v, (int, float)) or isinstance(v, bool)
               or not math.isfinite(v) or v < 0 for k, v in new.items()):
            c["invalid"] += 1
            continue
        adds = {k: float(v) for k, v in sorted(new.items()) if old.get(k) is None}
        if not adds:
            c["nothing_new"] += 1
            continue
        seen.add(mid)
        out.append({"schema": 1, "policy": POLICY, "match_id": mid,
                    "utc_year": m.scheduled_at.year, "additions": adds,
                    "prewrite_hash": _sha(_storage(m)), "source_stats_hash": _sha(old)})
    c["staged_matches"] = len(out)
    c["new_stat_values"] = sum(len(x["additions"]) for x in out)
    return out, c


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
        rows, counts = stage(_load(a.history_dir), _read(a.input))
        with (a.out_dir / "stage.jsonl").open("w") as fp:
            for r in rows:
                fp.write(json.dumps(r, sort_keys=True, allow_nan=False) + "\n")
        res = {"schema": 1, "mode": "stage", "counts": counts,
               "changed_years": sorted({r["utc_year"] for r in rows}),
               "production_mutated": False, "provider_requests": 0}
    elif a.mode == "write":
        rows = _read(a.stage_file)
        matches = _load(a.history_dir)
        by_id = {str(m.match_id): m for m in matches}
        for r in rows:
            m = by_id[r["match_id"]]
            if _sha(_storage(m)) != r["prewrite_hash"] or _sha(dict(m.stats or {})) != r["source_stats_hash"]:
                raise SystemExit("Canonical row changed since stage: " + r["match_id"])
            m.stats = {**(m.stats or {}), **r["additions"]}
        years = sorted({int(r["utc_year"]) for r in rows})
        for y in years:
            ids = {r["match_id"] for r in rows if int(r["utc_year"]) == y}
            write_exact_stats_partition(a.history_dir, y, matches, ids)
        res = {"schema": 1, "mode": "write", "updated": len(rows), "changed_years": years,
               "new_stat_values": sum(len(r["additions"]) for r in rows),
               "production_mutated": False, "provider_requests": 0}
    else:
        res = verify_readback(_load(a.before_dir), _load(a.history_dir), _read(a.stage_file))
    (a.out_dir / "report.json").write_text(json.dumps(res, sort_keys=True, indent=2) + "\n")
    print(json.dumps(res, sort_keys=True))


if __name__ == "__main__":
    main()
