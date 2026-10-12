#!/usr/bin/env python3
"""Read-only inventory of independent provider participant-ID crosswalk options.

Never maps by names, score/date-only matching, or approximate timestamps.
Never writes CDB. Every result is an aggregate; no private source rows logged.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

import pandas as pd

from blinq_season_cdb_gate import (
    source_rows, load_dict, p_id, provider_event_id, utc_start, sha256,
)

YEARS=tuple(range(2021,2026))

def sides(ctx):
    """Raw original participant IDs; require agreement between two context aliases."""
    identity=ctx.get("_tbt_event_identity")
    options=[]
    if isinstance(identity,dict):
        h,a=p_id(identity.get("home")),p_id(identity.get("away"))
        if h and a and h!=a: options.append((h,a))
    h,a=p_id(ctx.get("homeTeam")),p_id(ctx.get("awayTeam"))
    if h and a and h!=a:options.append((h,a))
    if len(set(options))>1:
        return None
    return options[0] if options else None

def pair(a,b):
    a,b=p_id(a),p_id(b)
    return tuple(sorted((a,b))) if a and b and a!=b else None

def date_utc(epoch):
    return pd.Timestamp(epoch,unit="s",tz="UTC").date().isoformat()

def canonical_index(history, sha):
    if set(sha)!={f"history-{y}.parquet" for y in YEARS}:
        raise ValueError("All five expected partitions required")
    counts=Counter()
    source_pair=defaultdict(list)
    canonical_pair=defaultdict(list)
    event_pair=defaultdict(list)
    for year in YEARS:
        name=f"history-{year}.parquet"
        path=Path(history)/name
        if sha256(path)!=sha[name]:
            raise ValueError("CDB Parquet SHA changed: "+name)
        columns=["match_id","tour","scheduled_at","player1_id","player2_id",
                 "winner_id","status","provider_context_json"]
        df=pd.read_parquet(path,columns=columns)
        counts["canonical_rows_scanned"]+=len(df)
        for values in df.itertuples(index=False,name=None):
            record=dict(zip(columns,values))
            tour=str(record["tour"]).lower()
            if tour not in ("atp","wta"):continue
            try:
                ctx=load_dict(record["provider_context_json"])
            except (ValueError,TypeError):
                counts["invalid_canonical_context"]+=1;continue
            time=utc_start(record["scheduled_at"])
            if time is None:continue
            counts["canonical_with_utc_clock"]+=1
            par=sides(ctx)
            if par:
                counts["canonical_with_original_provider_pair"]+=1
                source_pair[(tour,pair(*par))].append((time,record,ctx,par))
            else:counts["canonical_without_provider_pair"]+=1
            cp=pair(record["player1_id"],record["player2_id"])
            if cp:
                canonical_pair[(tour,cp)].append((time,record,ctx,par))
            eid=provider_event_id(ctx)
            if eid:
                event_pair[(tour,str(eid))].append((time,record,ctx,par))
    return source_pair,canonical_pair,event_pair,counts

def compare(sources,source_pair,canonical_pair,event_pair,counts):
    mode={"provider_pair":source_pair,"canonical_player_pair":canonical_pair}
    examples=[]
    for kind,index in mode.items():
        summary=Counter()
        deltas=Counter()
        for (tour,eid),rec in sources.items():
            raw=rec["raw"];par=pair(raw["home_id"],raw["away_id"])
            if not par:continue
            matches=index.get((tour,par),[])
            if not matches:summary["no_shared_pair"]+=1;continue
            summary["source_events_with_any_shared_pair"]+=1
            same_clock=[x for x in matches if x[0]==rec["ts"]]
            same_day=[x for x in matches if date_utc(x[0])==date_utc(rec["ts"])]
            if len(same_clock)!=1:
                summary["no_unique_exact_utc_clock"]+=1
                if same_day:summary["some_same_utc_day"]+=1
                continue
            when,can,ctx,cprovider=same_clock[0]
            summary["one_exact_pair_and_clock"]+=1
            if kind=="provider_pair":
                if not cprovider:raise AssertionError("missing provider pair")
                if tuple(cprovider) not in ((raw["home_id"],raw["away_id"]), (raw["away_id"],raw["home_id"])):
                    summary["provider_pair_disagreement"]+=1;continue
            eid_in_cdb=provider_event_id(ctx)
            if eid_in_cdb==eid:summary["same_event_id"]+=1
            else:summary["different_event_id"]+=1
            if str(can["status"]).lower() not in ("finished","completed","ended"):
                summary["canonical_not_finished"]+=1;continue
            p1,p2=str(can["player1_id"]),str(can["player2_id"])
            if kind=="provider_pair":
                # Critical: provider side IDs may be from a different namespace
                # than the canonical p1 and p2 IDs. Never infer orientation here.
                if (p1,p2)==(raw["home_id"],raw["away_id"]):home_p1=True
                elif (p2,p1)==(raw["home_id"],raw["away_id"]):home_p1=False
                else:
                    summary["no_verified_canonical_player_mapping"]+=1;continue
            else:
                home_p1=(p1==raw["home_id"])
            winner=raw["home_id"] if raw["winner_code"]=="1" else raw["away_id"]
            if str(can["winner_id"])!=str(winner):
                summary["winner_mismatch"]+=1;continue
            summary["strict_all_but_event_namespace"]+=1
            if eid_in_cdb==eid:
                summary["fully_exact_same_event_namespace"]+=1
        counts.update({kind+"_"+k:v for k,v in summary.items()})
    collision=Counter()
    for (tour,eid),rec in sources.items():
        matches=event_pair.get((tour,eid),[])
        if matches:
            collision["overlapping_event_id_strings"]+=1
            if any(x[0]==rec["ts"] for x in matches):collision["same_clock"]+=1
            else:collision["different_clock"]+=1
            matching_sides=any(x[3] and pair(*x[3])==pair(rec["raw"]["home_id"],rec["raw"]["away_id"]) for x in matches)
            if matching_sides:collision["same_original_participant_pair"]+=1
    counts.update({"event_id_collision_"+k:v for k,v in collision.items()})
    return counts

def run(sources_dir,history_dir,years_file,out_file):
    sha=json.loads(Path(years_file).read_text())
    sources,counts=source_rows(sources_dir)
    sp,cp,ep,canonical=canonical_index(history_dir,sha)
    counts.update(canonical)
    compare(sources,sp,cp,ep,counts)
    report={"schema":1,"state":"READ_ONLY_CROSS_NAMESPACE_EVIDENCE",
            "source_rows_eligible":len(sources),"canonical_sha256":sha,
            "counts":dict(sorted(counts.items())),
            "rights_verified":False,"independent_cross_provider_id_bridge":False,
            "no_heuristic_name_join":True,"write_authorized":False,
            "cdb_modified":False}
    Path(out_file).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-dir",required=True);p.add_argument("--history-dir",required=True)
    p.add_argument("--year-shas",required=True);p.add_argument("--out",required=True)
    args=p.parse_args()
    print(json.dumps(run(args.source_dir,args.history_dir,args.year_shas,args.out)["counts"],sort_keys=True))
