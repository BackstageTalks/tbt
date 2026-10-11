"""Strict null-only replay of uploaded, source-attested 2020-2025 set/game CDB delta.

The guarded workflow owns global writer lock, immutable rollback backup,
remote CAS, manifest-last publish and independent full-year persisted reread.
No provider API use; historical postmatch scores, never prematch features.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import timezone
import gzip
import hashlib
import json
from pathlib import Path
import re

import pandas as pd
from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_manifest, update_year_manifest

SOURCE_TAG = "blinq-audited-source-cell-delta-38123115526"
STAGE_SHA = "73387f3febca5c44ed4187d0b0e5fd0abe57a23e325e1c615332d7315d634f8c"
REPORT_SHA = "4cd96d2237c51fb530a60cdfda12d2a80ea1dfc292491b9db62f17da87b83c55"
YEARS = (2020, 2021, 2022, 2023, 2024, 2025)
FIELDS = frozenset({
    "p1_sets_won", "p2_sets_won", "p1_games_won", "p2_games_won",
    "total_sets", "total_games", "p1_first_set_won", "p2_first_set_won",
    "p1_second_set_won", "p2_second_set_won", "straight_sets",
    "tiebreak_sets", "deciding_set", "p1_set1_games", "p2_set1_games",
    "p1_set2_games", "p2_set2_games"
})
FLAGS = frozenset({"p1_first_set_won","p2_first_set_won","p1_second_set_won",
                   "p2_second_set_won","straight_sets","deciding_set"})
SHA = re.compile(r"[a-f0-9]{64}\Z")
SCORE_ROWS = 8685
SCORE_CELLS = 111653


def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as inp:
        for block in iter(lambda: inp.read(2 * 1024 * 1024),b""):
            h.update(block)
    return h.hexdigest()


def verified_stage(stage_file, report_file):
    if digest(stage_file)!=STAGE_SHA or digest(report_file)!=REPORT_SHA:
        raise ValueError("Pinned source-stage SHA256 mismatch")
    report=json.loads(Path(report_file).read_text())
    if (report.get("schema")!=1
            or report.get("candidate_stage_rows")!=SCORE_ROWS
            or report.get("completed_match_score_comparison",{}).get(
                "stageable_score_missing_cells_read_only")!=SCORE_CELLS
            or report.get("canonical",{}).get("year_partitions")!=78
            or report.get("safety",{}).get("no_cdb_writes") is not True):
        raise ValueError("Immutable source comparison report changed")
    entries=[]
    owners=set()
    counts=Counter()
    with gzip.open(stage_file,"rt",encoding="utf-8") as inp:
        for line in inp:
            if not line.strip():
                continue
            row=json.loads(line)
            mid=row.get("canonical_match_id")
            year=row.get("canonical_year")
            adds=row.get("add_only_missing_score_fields")
            if (row.get("schema")!=1
                or row.get("policy")!="READ_ONLY_CANDIDATE_NOT_WRITER_APPROVED_POSTMATCH_ONLY"
                or not isinstance(mid,str) or not mid or mid in owners
                or year not in YEARS
                or not isinstance(adds,dict) or not adds or not set(adds)<=FIELDS
                or not all(isinstance(row.get(k),str) and SHA.fullmatch(row[k]) for k in
                           ("canonical_year_sha256","canonical_existing_stats_sha256",
                            "source_sha256","source_observation_sha256"))
                or not isinstance(row.get("source_link"),dict)
                or row["source_link"].get("orientation") not in ("direct","swapped")
                or not all(isinstance(row.get(k),str) and row[k] for k in
                           ("source_record_date","match_player1_id",
                            "match_player2_id","match_winner_id"))):
                raise ValueError("Invalid source identity / stats claim")
            for key,value in adds.items():
                if (isinstance(value,bool) or not isinstance(value,int) or value<0
                    or value>(1 if key in FLAGS else 99)):
                    raise ValueError("Out-of-domain original tennis score value: "+key)
            owners.add(mid)
            counts[year]+=len(adds)
            entries.append(row)
    if len(entries)!=SCORE_ROWS or sum(counts.values())!=SCORE_CELLS:
        raise ValueError("Source-stage expected rows/fields changed")
    return entries,dict(counts)


def load_year(directory, year, release=None):
    directory=Path(directory)
    path=directory/f"history-{year}.parquet"
    meta=(load_manifest(directory).get("years") or {}).get(str(year)) or {}
    sha=digest(path)
    if (meta.get("asset")!=path.name or meta.get("sha256")!=sha
        or release is not None and release.get(path.name)!="sha256:"+sha):
        raise ValueError("Year manifest / release SHA256 mismatch: "+str(year))
    frame=pd.read_parquet(path)
    if (len(frame)!=int(meta.get("rows",-1))
        or frame.match_id.astype(str).duplicated().any()
        or "stats_json" not in frame.columns):
        raise ValueError("Canonical duplicate/row count inconsistency")
    return frame,meta


def patch_year(frame, rows, year, year_sha):
    result=frame.copy(deep=True)
    index=dict(zip(frame.match_id.astype(str),frame.index))
    changed=set()
    additions=0
    for item in rows:
        mid=item["canonical_match_id"]
        if item["canonical_year_sha256"]!=year_sha or mid not in index:
            raise ValueError("Stale year / nonexistent CDB identity")
        ix=index[mid]
        old=frame.loc[ix]
        date=pd.Timestamp(old["scheduled_at"]).tz_convert(timezone.utc).date().isoformat()
        if (str(old["player1_id"])!=item["match_player1_id"]
            or str(old["player2_id"])!=item["match_player2_id"]
            or str(old["winner_id"])!=item["match_winner_id"]
            or date!=item["source_record_date"]
            or pd.Timestamp(old["scheduled_at"]).year!=year):
            raise ValueError("Stale match/player/winner/date identity")
        raw=old["stats_json"]
        if hashlib.sha256(str(raw).encode("utf-8")).hexdigest()!=item["canonical_existing_stats_sha256"]:
            raise ValueError("Original per-match stats SHA precondition changed")
        old_stats=json.loads(raw)
        if not isinstance(old_stats,dict):
            raise ValueError("Malformed existing stats")
        new_stats=dict(old_stats)
        for k,v in item["add_only_missing_score_fields"].items():
            if k in new_stats and new_stats[k] is not None:
                raise ValueError("Existing populated CDB value must never be overwritten: "+k)
            new_stats[k]=v
            additions+=1
        result.at[ix,"stats_json"]=json.dumps(new_stats,sort_keys=True,ensure_ascii=False,
                                               separators=(",",":"),allow_nan=False)
        changed.add(mid)
    cols=[k for k in frame.columns if k!="stats_json"]
    pd.testing.assert_frame_equal(result[cols],frame[cols],check_dtype=True)
    keep=~frame.index.isin([index[x] for x in changed])
    pd.testing.assert_series_equal(frame.loc[keep,"stats_json"],result.loc[keep,"stats_json"])
    return result,{"year":year,"changed_matches":len(changed),
                   "added_values":additions,"canonical_rows_checked":len(frame),
                   "existing_values_overwritten":0}


def execute(mode,stage,report,before,after,release_json):
    if mode not in ("dry-run","write","verify"):
        raise ValueError("Invalid import mode")
    before,after=Path(before),Path(after)
    if mode=="write" and before.resolve()==after.resolve():
        raise ValueError("In-place canonical writer forbidden")
    entries,per_year=verified_stage(stage,report)
    by_year=defaultdict(list)
    for row in entries:
        by_year[row["canonical_year"]].append(row)
    release=json.loads(Path(release_json).read_text())
    remote={x["name"]:x["digest"] for x in release["assets"]}
    # The two original manifests must be part of the same pinned release.
    for name in ("history_manifest.json","_tbt_bundle_manifest.json"):
        if remote.get(name)!="sha256:"+digest(before/name):
            raise ValueError("Original release manifest changed")
    totals=[]
    for y in YEARS:
        current,meta=load_year(before,y,remote)
        expected,summary=patch_year(current,by_year[y],y,meta["sha256"])
        target=after/f"history-{y}.parquet"
        if mode=="write":
            after.mkdir(parents=True,exist_ok=True)
            tmp=target.with_name(target.name+".tmp")
            try:
                expected.to_parquet(tmp,engine="pyarrow",compression="zstd",index=False)
                pd.testing.assert_frame_equal(pd.read_parquet(tmp),expected,check_dtype=True)
                tmp.replace(target)
                update_year_manifest(after,y,{"sha256":digest(target),
                                               "rows":len(expected),"bytes":target.stat().st_size})
            finally:
                if tmp.exists():tmp.unlink()
        if mode=="verify":
            actual,_=load_year(after,y)
            pd.testing.assert_frame_equal(actual,expected,check_dtype=True)
        summary.update({"before_sha256":meta["sha256"],
                        "after_sha256":digest(target) if mode!="dry-run" else None})
        totals.append(summary)
    if sum(x["changed_matches"] for x in totals)!=SCORE_ROWS:
        raise ValueError("Unexpected linked match row count")
    if sum(x["added_values"] for x in totals)!=SCORE_CELLS:
        raise ValueError("Unexpected missing-cell total")
    return {"schema":1,"status":"verified" if mode=="verify" else "verified_"+mode,
            "years":YEARS,"year_reports":totals,
            "changed_matches":SCORE_ROWS,"added_values":SCORE_CELLS,
            "existing_values_overwritten":0,"source_stage_sha256":STAGE_SHA,
            "source_report_sha256":REPORT_SHA,"canonical_rows_checked":sum(
                x["canonical_rows_checked"] for x in totals),
            "production_mutated":False,"model_trained":False,"provider_api_requests":0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode",required=True,choices=("dry-run","write","verify"))
    for key in ("stage","report","before","after","release_json","out"):
        p.add_argument("--"+key.replace("_","-"),required=True,type=Path)
    args=p.parse_args()
    result=execute(args.mode,args.stage,args.report,args.before,args.after,args.release_json)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
