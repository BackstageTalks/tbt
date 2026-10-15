#!/usr/bin/env python3
"""Strict NULL-only native Sackmann converted breakpoint count import.

Writes solely to a local coherent CDB copy. Release publication, immutable
backup, source manifest CAS, writer lock and remote readback belong to CI.
Fixed hash shard defines a stable replay scope; never auto-advance shard.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,re
from collections import Counter
from datetime import timezone
from pathlib import Path
from audit_pbp_source_vs_current_cdb import FILES
from audit_cdb_sackmann_bp_count_gap import candidate,COUNTS
from recover_cdb_sackmann_breakpoints import (_load,source_match_id,digest,SOURCE_REVISION)
from recover_cdb_opponent_service_rates import _sha,_storage,verify_readback
from offline_exact_cdb_write import write_exact_stats_partition
POLICY="sackmann_proven_hist_js_bp_converted_counts_null_only_shard_v1"

def in_scope(match_id,modulus,index):
    return int(str(match_id).rsplit(":",1)[-1][:8],16) % modulus == index

def stage(matches,source,*,modulus=16,index=0,canonical_year=2018):
    if not 0<=index<modulus or modulus<1:
        raise ValueError("Invalid fixed hash shard")
    by_id={str(m.match_id):m for m in matches if str(m.match_id).startswith("hist-js:")}
    stats=Counter()
    eligible={}
    conflicts=set()
    source_digests={}
    for path in sorted(source.rglob("*.csv")):
        rel=path.relative_to(source).as_posix()
        if not any(re.fullmatch(expr,rel) for expr in FILES):
            continue
        tour=rel.split("/",1)[0]
        stats["source_files"]+=1
        with path.open(encoding="utf-8-sig",newline="") as stream:
            for lineno,row in enumerate(csv.DictReader(stream),2):
                mid,kind=source_match_id(tour,path,row,lineno)
                match=by_id.get(mid)
                if match is None:
                    continue
                if (canonical_year is not None and match.scheduled_at.year != canonical_year):
                    continue
                if not in_scope(mid,modulus,index):
                    continue
                stats["matched_in_fixed_shard"]+=1
                if mid in conflicts or mid in eligible:
                    eligible.pop(mid,None)
                    conflicts.add(mid)
                    stats["duplicate_source_target_quarantined"]+=1
                    continue
                additions,reason=candidate(match,row,tour,kind,path)
                stats[reason]+=1
                if not additions:
                    continue
                if rel not in source_digests:
                    source_digests[rel]=digest(path)
                eligible[mid]={
                    "schema":1,"policy":POLICY,"match_id":mid,
                    "utc_year":match.scheduled_at.astimezone(timezone.utc).year,
                    "prewrite_hash":_sha(_storage(match)),
                    "source_stats_hash":_sha(match.stats or {}),
                    "source":{"commit":SOURCE_REVISION,"path":rel,
                              "sha256":source_digests[rel],"line":lineno,
                              "winner_source_id":str(row["winner_id"]),
                              "loser_source_id":str(row["loser_id"])},
                    "shard":{"modulus":modulus,"index":index},
                    "additions":additions,
                }
    rows=[eligible[x] for x in sorted(eligible)]
    if not stats["source_files"] or not stats["matched_in_fixed_shard"]:
        raise ValueError("Pinned source or canonical fixed shard missing")
    stats["staged_matches"]=len(rows)
    stats["new_stat_values"]=sum(len(row["additions"]) for row in rows)
    return rows,dict(stats)

def write_local(matches,staged,source,*,modulus=16,index=0,canonical_year=2018):
    expected,_=stage(matches,source,modulus=modulus,index=index,canonical_year=canonical_year)
    if expected!=staged or len({x["match_id"] for x in staged})!=len(staged):
        raise ValueError("Pinned source, identity or baseline changed since staging")
    by_id={str(m.match_id):m for m in matches}
    years=set()
    for row in staged:
        if row.get("policy")!=POLICY or set(row["additions"])-set(COUNTS):
            raise ValueError("Invalid count field or policy")
        if row.get("shard")!={"modulus":modulus,"index":index}:
            raise ValueError("Unapproved shard switch")
        match=by_id[row["match_id"]]
        if row["prewrite_hash"]!=_sha(_storage(match)):
            raise ValueError("Changed canonical baseline")
        if row["source_stats_hash"]!=_sha(match.stats or {}):
            raise ValueError("Changed stats baseline")
        for k,v in row["additions"].items():
            if match.stats.get(k) is not None:
                raise ValueError("Refusing existing CDB count overwrite")
            if not isinstance(v,int) or isinstance(v,bool) or v<0:
                raise ValueError("Invalid converted break-point integer")
        years.add(int(row["utc_year"]))
    for row in staged:
        match=by_id[row["match_id"]]
        match.stats={**match.stats,**row["additions"]}
    return sorted(years)

def write_exact(history,changed_matches,staged):
    years=sorted({int(row["utc_year"]) for row in staged})
    for year in years:
        ids={row["match_id"] for row in staged if int(row["utc_year"])==year}
        write_exact_stats_partition(history,year,changed_matches,ids,
                                     approved_count_fields=frozenset(COUNTS))
    return years

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=("stage","write","verify"),required=True)
    p.add_argument("--history-dir",type=Path,required=True)
    p.add_argument("--source-dir",type=Path)
    p.add_argument("--before-dir",type=Path)
    p.add_argument("--stage-file",type=Path)
    p.add_argument("--out-dir",type=Path,required=True)
    p.add_argument("--shard-modulus",type=int,default=16)
    p.add_argument("--canonical-year",type=int,default=2018)
    p.add_argument("--shard-index",type=int,default=0)
    a=p.parse_args()
    a.out_dir.mkdir(parents=True,exist_ok=True)
    if a.mode=="stage":
        if not a.source_dir:p.error("--source-dir required for stage")
        rows,counts=stage(_load(a.history_dir),a.source_dir,modulus=a.shard_modulus,index=a.shard_index,
                          canonical_year=a.canonical_year)
        with (a.out_dir/"stage.jsonl").open("w") as stream:
            for row in rows:stream.write(json.dumps(row,sort_keys=True,allow_nan=False)+"\n")
        result={"schema":1,"mode":"stage","counts":counts,
                "changed_years":sorted({r["utc_year"] for r in rows}),
                "source_commit":SOURCE_REVISION,
                "shard":{"modulus":a.shard_modulus,"index":a.shard_index},
                "canonical_year":a.canonical_year,
                "production_mutated":False,"provider_requests":0}
    elif a.mode=="write":
        if not a.source_dir or not a.stage_file:p.error("--stage-file and --source-dir required")
        rows=[json.loads(line) for line in a.stage_file.read_text().splitlines() if line.strip()]
        matches=_load(a.history_dir)
        years=write_local(matches,rows,a.source_dir,modulus=a.shard_modulus,index=a.shard_index,
                          canonical_year=a.canonical_year)
        if years:write_exact(a.history_dir,matches,rows)
        result={"schema":1,"mode":"write","updated":len(rows),
                "new_stat_values":sum(len(r["additions"]) for r in rows),
                "changed_years":years,"production_mutated":False,"provider_requests":0}
    else:
        if not a.before_dir or not a.stage_file:p.error("--before-dir and --stage-file required")
        rows=[json.loads(line) for line in a.stage_file.read_text().splitlines() if line.strip()]
        result=verify_readback(_load(a.before_dir),_load(a.history_dir),rows)
    (a.out_dir/"report.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))
if __name__=="__main__":main()
