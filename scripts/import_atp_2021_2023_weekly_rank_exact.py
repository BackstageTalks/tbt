"""Add exact, historic point-in-time ATP weekly ranks to current CDB year partitions.

Strict null-only canonical rank patch. No API, no release writes, no model action.
An external governed workflow owns lock, immutable remote backup, CAS and release.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import shutil
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_manifest, update_year_manifest

YEARS = (2021, 2022, 2023)
FIELDS = ("player1_rank", "player2_rank")
PROVENANCE = "_tbt_rank_provenance"
SOURCE = "atp_rankings_ishanjha_weekly"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def absent(v):
    return v is None or bool(pd.isna(v))


def bounded_rank(value):
    if isinstance(value, bool) or isinstance(value, (list, dict)):
        raise ValueError("Invalid rank value")
    text = str(value or "").strip()
    if not text.isdecimal():
        raise ValueError("Rank must be integer digits")
    n = int(text)
    if n < 1 or n > 30000:
        raise ValueError("Rank outside historical ATP range")
    return n


def get_pin(pin_file, stage_file, report_file):
    p = json.loads(Path(pin_file).read_text())
    r = json.loads(Path(report_file).read_text())
    if (p.get("upstream_git_commit") != "247f2f5e86b9e142a7ead7b0e8b3dfb5ee6abb28"
            or not isinstance(p.get("years"), dict)
            or set(p["years"]) != {str(y) for y in YEARS}
            or r.get("schema") != 1 or r.get("stage_rows") != 2212
            or r.get("rapidapi_requests") != 0 or r.get("production_mutated") is not False
            or r.get("local_partitions_written") is not False
            or r.get("counts", {}).get("updated") != 2212
            or r.get("counts", {}).get("player1_rank_filled") != 2212
            or r.get("counts", {}).get("player2_rank_filled") != 2212
            or r.get("counts", {}).get("stale_snapshot_rejected", 0) != 0):
        raise ValueError("Unrecognized current ATP weekly source cohort or expected delta")
    if not Path(stage_file).is_file():
        raise ValueError("Private rank stage not found")
    return p, r


def year_frame(directory, year, pin):
    manifest = load_manifest(directory)
    entry = (manifest.get("years") or {}).get(str(year), {})
    path = Path(directory) / f"history-{year}.parquet"
    actual = digest(path)
    if entry.get("sha256") != actual or entry.get("asset") != path.name:
        raise ValueError("Partition/manifest mismatch: " + str(year))
    if pin is not None and pin["years"][str(year)] != actual:
        raise ValueError("Canonical 2021–2023 year changed since ranked source dry-run")
    frame = pd.read_parquet(path)
    if int(entry.get("rows", -1)) != len(frame):
        raise ValueError("Year row count drift")
    expected = {"match_id", "tour", "scheduled_at", "player1_id", "player2_id",
                "player1_name", "player2_name", "player1_rank", "player2_rank",
                "provider_context_json"}
    if not expected.issubset(frame.columns):
        raise ValueError("Canonical schema lacks columns")
    ids = frame["match_id"].astype(str)
    if ids.duplicated().any() or (ids=="").any():
        raise ValueError("Canonical identities duplicate/invalid")
    return frame, entry


def stage_rows(file):
    items = [json.loads(line) for line in Path(file).read_text().splitlines() if line.strip()]
    if len(items) != 2212:
        raise ValueError("Unexpected staged source count")
    seen = set()
    for item in items:
        mid = str(item.get("match_id") or "")
        if not mid or mid in seen or item.get("schema") != 1 or item.get("source") != SOURCE:
            raise ValueError("Invalid or duplicate stage identity/source")
        seen.add(mid)
    return items


def apply(before, rows, *, expected_matches=2212, expected_fields=4424, expected_stale=0):
    out = {year: frame.copy(deep=True) for year, frame in before.items()}
    indexes = {year: dict(zip(frame["match_id"].astype(str), frame.index)) for year,frame in before.items()}
    counts = Counter()
    modified = set()
    for item in rows:
        mid = str(item["match_id"])
        stamp = pd.Timestamp(item["scheduled_at"])
        if stamp.tzinfo is None:
            raise ValueError("Naive source stage timestamp")
        stamp = stamp.tz_convert("UTC")
        year = stamp.year
        if year not in YEARS or mid not in indexes[year]:
            raise ValueError("Source match not present in exactly expected year")
        index = indexes[year][mid]
        original = before[year].loc[index]
        if (str(original["tour"]).lower() != "atp"
                or pd.Timestamp(original["scheduled_at"]).tz_convert("UTC") != stamp
                or any(str(original[k]) != str(item[k]) for k in
                       ("player1_id", "player1_name", "player2_id", "player2_name"))):
            raise ValueError("Canonical identity or tour mismatch")
        source_week = date.fromisoformat(str(item["source_week"]))
        age = (stamp.date() - source_week).days
        if age < 1 or age > 14:
            counts["stale_or_same_day_excluded"] += 1
            continue
        nums = [bounded_rank(item["incoming_" + key]) for key in FIELDS]
        for key, val in zip(FIELDS, nums):
            prior = original[key]
            source_prior = item.get("existing_" + key)
            if absent(prior) != (source_prior is None):
                raise ValueError("Original rank precondition changed")
            if not absent(prior) and (float(prior)!=val or int(prior)!=int(source_prior)):
                raise ValueError("Forbidden rank collision")
        if all(not absent(original[k]) for k in FIELDS):
            raise ValueError("Duplicated already complete rank stage")
        context_raw = original["provider_context_json"]
        context = json.loads(context_raw) if not absent(context_raw) else {}
        if not isinstance(context, dict):
            raise ValueError("Invalid canonical provider context")
        mark = {"source": SOURCE, "as_of": source_week.isoformat()+"T00:00:00+00:00",
                "point_in_time": True}
        if PROVENANCE in context and context[PROVENANCE] != mark:
            raise ValueError("Existing rank provenance conflict")
        context[PROVENANCE] = mark
        out[year].at[index, "provider_context_json"] = json.dumps(
            context, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for key,val in zip(FIELDS,nums):
            if absent(original[key]):
                out[year].at[index,key] = val
                counts[key+"_filled"] += 1
        counts["changed_matches"] += 1
        modified.add((year,mid))
    if (counts["changed_matches"]!=expected_matches or
            sum(counts[k+"_filled"] for k in FIELDS)!=expected_fields or
            counts["stale_or_same_day_excluded"]!=expected_stale):
        raise ValueError("Unexpected source/CDB delta; stop rather than publish")
    # Entire-source other columns and all non-updated rows must be unchanged.
    for year in YEARS:
        f=before[year]
        g=out[year]
        ignore={"player1_rank","player2_rank","provider_context_json"}
        cols=[c for c in f.columns if c not in ignore]
        pd.testing.assert_frame_equal(f[cols],g[cols],check_dtype=True)
        mask=~f["match_id"].astype(str).isin({mid for y,mid in modified if y==year})
        pd.testing.assert_frame_equal(f.loc[mask],g.loc[mask],check_dtype=True)
    return out,dict(counts)


def run(mode, before_dir, after_dir, stage_file, pin_file, dry_report_file):
    if mode not in ("dry-run","write","verify"):
        raise ValueError("Unknown rank import mode")
    before_dir, after_dir=Path(before_dir),Path(after_dir)
    pin,_=get_pin(pin_file,stage_file,dry_report_file)
    frames={y:year_frame(before_dir,y,pin)[0] for y in YEARS}
    expected,counts=apply(frames,stage_rows(stage_file))
    if mode=="write":
        if before_dir.resolve()==after_dir.resolve():
            raise ValueError("In-place production CDB mutation forbidden")
        after_dir.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(before_dir/"history_manifest.json",after_dir/"history_manifest.json")
        for year in YEARS:
            target=after_dir/f"history-{year}.parquet"
            tmp=target.with_suffix(".parquet.tmp")
            try:
                expected[year].to_parquet(tmp,engine="pyarrow",compression="zstd",index=False)
                pd.testing.assert_frame_equal(pd.read_parquet(tmp),expected[year],check_dtype=True)
                tmp.replace(target)
                update_year_manifest(after_dir,year,{"sha256":digest(target),
                    "bytes":target.stat().st_size,"rows":len(expected[year])},
                    extra={"coverage_status":"ATP_pinned_weekly_pre_match_rank_fill"})
            finally:
                if tmp.exists():
                    tmp.unlink()
    elif mode=="verify":
        for year in YEARS:
            actual,_=year_frame(after_dir,year,pin=None)
            pd.testing.assert_frame_equal(actual,expected[year],check_dtype=True)
    return {
        "schema":1,"mode":mode,
        "status":"verified_exact_full_year" if mode=="verify" else "validated_"+mode,
        "changed_years":list(YEARS),"counts":counts,
        "total_matches_rechecked":sum(map(len,frames.values())),
        "existing_nonnull_ranks_overwritten":0,
        "year_baseline_sha256":pin["years"],
        "year_after_sha256":{str(y):digest(after_dir/f"history-{y}.parquet") for y in YEARS}
           if mode!="dry-run" else {},
        "source_stage_sha256":digest(stage_file),
        "upstream_sqlite_sha256":pin["upstream_source_sha256"],
        "production_mutated_by_script":False,"model_trained":False,
        "model_promoted":False,"provider_requests":0,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=("dry-run","write","verify"),required=True)
    for name in ("before_dir","after_dir","stage_file","pin_file","dry_report_file","out"):
        p.add_argument("--"+name.replace("_","-"),type=Path,required=True)
    args=p.parse_args()
    result=run(args.mode,args.before_dir,args.after_dir,args.stage_file,
               args.pin_file,args.dry_report_file)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
