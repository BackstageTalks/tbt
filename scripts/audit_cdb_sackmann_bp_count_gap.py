#!/usr/bin/env python3
"""Read-only census of source-native BP converted counts missing in current CDB.

Sackmann bpFaced/bpSaved are match-level posthoc counts, not prematch features.
This script never mutates CDB, model or original source.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math,re
from collections import Counter
from datetime import timezone
from pathlib import Path
from audit_pbp_source_vs_current_cdb import FILES,valid
from import_historical_match_foundation import _stats
from recover_cdb_sackmann_breakpoints import (_load,source_match_id,
                                              _valid_cdb_lineage)
COUNTS=("p1_break_points_won","p2_break_points_won")

def source_bp_counts(row):
    raw=valid(row)
    if raw is None:
        return None
    return {"p1_break_points_won":int(raw["l_bpFaced"]-raw["l_bpSaved"]),
            "p2_break_points_won":int(raw["w_bpFaced"]-raw["w_bpSaved"])}

def candidate(match,row,tour,kind,path):
    if not _valid_cdb_lineage(match,row,tour,kind,path):
        return {}, "lineage_rejected"
    counts=source_bp_counts(row)
    if counts is None:
        return {}, "invalid_full_match_or_serve_break_point_counts"
    previous=match.stats
    if not isinstance(previous,dict):
        return {}, "invalid_canonical_stats"
    known=_stats(row)
    for key,value in known.items():
        observation=previous.get(key)
        if observation is not None and (
            isinstance(observation,bool) or not isinstance(observation,(int,float))
            or not math.isfinite(observation) or abs(float(observation)-float(value))>1e-6):
            return {}, "known_source_stats_conflict"
    result={}
    rejected=0
    for key,num in counts.items():
        old=previous.get(key)
        if old is not None:
            if not isinstance(old,(int,float)) or isinstance(old,bool) or abs(old-num)>1e-6:
                rejected+=1
            continue
        if key=="p1_break_points_won":
            faced=float(row["l_bpFaced"])
            rate=previous.get("p1_break_point_return_win")
            opposite=previous.get("p2_break_point_serve_win")
        else:
            faced=float(row["w_bpFaced"])
            rate=previous.get("p2_break_point_return_win")
            opposite=previous.get("p1_break_point_serve_win")
        if (rate is not None and (faced<=0 and abs(rate)>1e-6 or
                faced>0 and abs(float(rate)-num/faced)>1e-6)):
            rejected+=1
            continue
        if opposite is not None and (faced<=0 and abs(opposite)>1e-6 or
                faced>0 and abs(float(opposite)-(faced-num)/faced)>1e-6):
            rejected+=1
            continue
        result[key]=num
    if not result:
        return {}, "existing_or_conflicting_count"
    return result,"eligible"

def census(history,source):
    index={str(m.match_id):m for m in _load(history) if str(m.match_id).startswith("hist-js:")}
    stats=Counter()
    stage={}
    conflicts=set()
    per_year=Counter()
    for path in sorted(source.rglob("*.csv")):
        rel=path.relative_to(source).as_posix()
        if not any(re.fullmatch(p,rel) for p in FILES):
            continue
        tour=rel.split("/",1)[0]
        stats["source_files"]+=1
        with path.open(encoding="utf-8-sig",newline="") as file:
            for number,row in enumerate(csv.DictReader(file),2):
                mid,kind=source_match_id(tour,path,row,number)
                record=index.get(mid)
                if record is None:continue
                stats["matching_cdb_ids"]+=1
                if mid in conflicts or mid in stage:
                    stage.pop(mid,None)
                    conflicts.add(mid)
                    stats["duplicate_source_target"]+=1
                    continue
                addition,why=candidate(record,row,tour,kind,path)
                stats[why]+=1
                if not addition:continue
                stage[mid]={"utc_year":record.scheduled_at.astimezone(timezone.utc).year,
                            "fields":addition}
    for x in stage.values():
        per_year[str(x["utc_year"])]+=1
        stats["eligible_stat_cells"]+=len(x["fields"])
    stats["eligible_unique_matches"]=len(stage)
    return {"schema":"BlinQ_BP_NATIVE_COUNT_CDB_GAP_V1",
            "canonical_input":"coherent_tbt_data_v1_SHA_verified",
            "source_revision":"83733587353df8a41f2fd4f516147d5aa83f5a8d",
            "source_rights":"Sackmann noncommercial attribution required",
            "counts":dict(sorted(stats.items())),
            "years":dict(sorted(per_year.items())),
            "canonical_writes":0,"production_model_changes":0}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--history-dir",type=Path,required=True)
    p.add_argument("--source-dir",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    report=census(a.history_dir,a.source_dir)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print("SACKMANN_BP_CONVERTED_COUNT_NULL_GAP",json.dumps(report,sort_keys=True))
if __name__=="__main__":main()
