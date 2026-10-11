#!/usr/bin/env python3
"""Read-only ACTUAL source-record-to-current-CDB field delta for uploaded match sidecars.

Exact canonical match_id + saved event UTC date, original player orientation and
full validated set-score consistency are mandatory. Distinguishes missing,
present/equal and conflicts per field. Does NOT authorize a writer.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import pandas as pd

def dump_hash(p):
    h=sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def numeric(value):
    if isinstance(value,bool) or value is None or value=="":return None
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError):return None

def positive_int(value):
    n=numeric(value)
    return int(n) if n is not None and n>=1 and int(n)==n else None

def nonneg_int(value):
    n=numeric(value)
    return int(n) if n is not None and 0<=n<=99 and int(n)==n else None

def cleanstr(value):
    return str(value or "").strip().lower().replace("_"," ")

def norm_surface(v):
    val=cleanstr(v)
    if val in ("hard","clay","grass","carpet"):return val
    if val in ("indoor hard","indoor_hard","hardcourt","hard court"):return "hard"
    if val in ("red clay","green clay"):return "clay"
    return None

def is_missing(v):
    if v is None:return True
    if isinstance(v,str):return v.strip().lower() in ("","none","null","unknown","nan","n/a")
    try:return bool(pd.isna(v))
    except (ValueError,TypeError):return False

def compare_field(counters, field, current, proposed):
    if proposed is None:return "absent_source"
    if is_missing(current):
        counters[field+"_missing_valid_source"]+=1
        return "missing"
    if isinstance(current,bool):
        equal=(proposed in (0,1,False,True) and int(current)==int(proposed))
    else:
        equal=(abs(float(current)-float(proposed))<1e-7 if
               numeric(current) is not None and numeric(proposed) is not None
               else cleanstr(current)==cleanstr(proposed))
    counters[field+"_already_equal" if equal else field+"_conflict"]+=1
    return "equal" if equal else "conflict"

def valid_set_score(sets, p1_sets, p2_sets, winner_player, best_of):
    """Whole-match completed standard match only; tiebreak extended formats quarantined."""
    if not isinstance(sets,list) or len(sets)<2 or len(sets)>5 or best_of not in (3,5):
        return None, "invalid_count_or_format"
    seq=[]
    wins=[0,0]
    for idx,item in enumerate(sets,1):
        if not isinstance(item,dict) or item.get("set")!=idx:
            return None,"missing_or_out_of_order_set"
        x,y=nonneg_int(item.get("player1_games")),nonneg_int(item.get("player2_games"))
        if x is None or y is None:return None,"invalid_games"
        a,b=max(x,y),min(x,y)
        if not ((a>=6 and a-b>=2) or (a==7 and b==6)):
            return None,"nonstandard_or_incomplete_set"
        wins[0 if x>y else 1]+=1
        seq.append((x,y))
    if (nonneg_int(p1_sets),nonneg_int(p2_sets))!=tuple(wins):
        return None,"sets_won_source_conflict"
    if len(seq)>best_of or max(wins)!=(best_of//2+1) or min(wins)+max(wins)!=len(seq):
        return None,"incomplete_or_unexpected_format"
    if winner_player not in (1,2) or wins[winner_player-1]!=max(wins):
        return None,"winner_conflict"
    p1=sum(x for x,y in seq);p2=sum(y for x,y in seq)
    s={
        "p1_sets_won":wins[0],"p2_sets_won":wins[1],
        "p1_games_won":p1,"p2_games_won":p2,
        "total_sets":len(seq),"total_games":p1+p2,
        "p1_first_set_won":int(seq[0][0]>seq[0][1]),
        "p2_first_set_won":int(seq[0][1]>seq[0][0]),
        "straight_sets":int(min(wins)==0),
        "tiebreak_sets":sum(set([x,y])==set([6,7]) for x,y in seq),
        "deciding_set":int(len(seq)==best_of),
    }
    for idx,(x,y) in enumerate(seq[:2],1):
        s[f"p1_set{idx}_games"]=x
        s[f"p2_set{idx}_games"]=y
    if len(seq)>1:
        s["p1_second_set_won"]=int(seq[1][0]>seq[1][1])
        s["p2_second_set_won"]=int(seq[1][1]>seq[1][0])
    return s,None

def load_sidecars(path):
    result={}
    sha={}
    for p in sorted(path.glob("blinq-uploaded-match-enrichment-*.jsonl.gz")):
        sha[p.name]=dump_hash(p)
        with gzip.open(p,"rt",encoding="utf-8") as f:
            for line in f:
                if not line.strip():continue
                v=json.loads(line)
                mid=str(v.get("match_id") or "")
                if not mid or mid in result:raise ValueError("Missing or duplicated exact source match ID")
                result[mid]=v
    return result,sha

def audit(history,release,uploaded,market,source):
    original,raw_sha=load_sidecars(uploaded)
    assets={v["name"]:v for v in release["assets"]}
    for name,d in raw_sha.items():
        assert assets[name]["digest"]=="sha256:"+d, "Source digest drift: "+name
    years=json.loads((history/"history_manifest.json").read_text())["years"]
    ids=set(original)
    matches={}
    cdb_ids=set()
    prefix_fields=["match_id","tour","scheduled_at","winner_id","player1_id","player2_id","player1_rank","player2_rank","best_of","indoor","surface","round_name","stats_json","provider_context_json"]
    per_year=Counter()
    for p in sorted(history.glob("history-????.parquet")):
        yyyy=re.search(r"history-(\d{4})\.parquet",p.name).group(1)
        sha=dump_hash(p)
        assert sha==years[yyyy]["sha256"]==assets[p.name]["digest"].split(":")[-1]
        df=pd.read_parquet(p,columns=prefix_fields)
        per_year[yyyy]=len(df)
        for m in df.itertuples(index=False,name=None):
            mid=str(m[0])
            if mid in ids:
                if mid in matches:raise ValueError("Duplicate candidate match ID in CDB")
                matches[mid]=dict(zip(prefix_fields,m))
    assert len(per_year)==78 and sum(per_year.values())>=994101
    core=Counter()
    score=Counter()
    missing_score_fields=Counter()
    already_score_fields=Counter()
    conflict_score_fields=Counter()
    missing_core_fields=Counter()
    matched_ids=0
    reviewed=[]
    annual=defaultdict(Counter)
    for mid,src in original.items():
        m=matches.get(mid)
        if m is None:
            core["missing_exact_cdb_match_id"]+=1
            continue
        matched_ids+=1
        year=pd.to_datetime(m["scheduled_at"],utc=True).year
        date=pd.to_datetime(m["scheduled_at"],utc=True).date().isoformat()
        if date!=src.get("scheduled_date_utc"):
            core["saved_source_date_mismatch"]+=1
            continue
        core["exact_match_and_date"]+=1
        annual[year]["matched"]+=1
        context=src.get("pre_match_context") or {}
        result=src.get("result_context") or {}
        link=src.get("link") or {}
        if not isinstance(context,dict) or not isinstance(result,dict) or link.get("orientation") not in ("direct","swapped"):
            core["incomplete_context_or_orientation"]+=1
            continue
        rankA=positive_int(context.get("player1_rank"));rankB=positive_int(context.get("player2_rank"))
        best=positive_int(context.get("best_of"))
        if best not in (3,5):best=None
        court=cleanstr(context.get("court"))
        indoor=1 if court=="indoor" else 0 if court=="outdoor" else None
        surf=norm_surface(context.get("surface"))
        source_fields=[
           ("player1_rank",m["player1_rank"],rankA),
           ("player2_rank",m["player2_rank"],rankB),
           ("best_of",m["best_of"],best),
           ("indoor",m["indoor"],indoor),
           ("surface",norm_surface(m["surface"]),surf)
        ]
        has_conflict=False
        for key,existing,observed in source_fields:
            if observed is None:continue
            state=compare_field(core,key,existing,observed)
            if state=="conflict":has_conflict=True
            if state=="missing":missing_core_fields[key]+=1
        # Rank point values do not have canonical top-level columns.
        for key in ("player1_rank_points","player2_rank_points"):
            if positive_int(context.get(key)) is not None:
                core[key+"_verified_source_candidate_only"]+=1
        for k in ("source_round","location","series"):
            if context.get(k):core[k+"_present_source_context"]+=1
        if result.get("sets"):
            score["set_tape_present"]+=1
        if result.get("comment") and re.search(r"retir|walk.?over|abandon|interrupt|suspend|postpon|cancel|w/o|unfinished",str(result.get("comment")),flags=re.I):
            score["termination_unsafe"]+=1
            continue
        winner=m["winner_id"]
        winner_side=(1 if winner==m["player1_id"] else 2 if winner==m["player2_id"] else None)
        vals,reason=valid_set_score(
            result.get("sets"),result.get("player1_sets"),result.get("player2_sets"),
            winner_side,positive_int(m["best_of"]) or best)
        if reason:
            score["not_score_approved_"+reason]+=1
            continue
        if has_conflict:
            score["valid_score_but_core_field_conflict"]+=1
            continue
        score["validated_source_full_match"]+=1
        st=json.loads(m["stats_json"] or "{}")
        missing={}
        conflicts={}
        equals=0
        for key,value in vals.items():
            target=st.get(key)
            if target is None:missing[key]=value
            elif numeric(target) is not None and abs(float(target)-float(value))<1e-7:equals+=1
            else:conflicts[key]=[target,value]
        if conflicts:
            score["conflicting_score_matches"]+=1
            score["conflicting_score_cells"]+=len(conflicts)
            for key in conflicts:conflict_score_fields[key]+=1
            continue
        if missing:
            score["stageable_score_matches_read_only"]+=1
            score["stageable_score_missing_cells_read_only"]+=len(missing)
            annual[year]["new_score_matches"]+=1
            annual[year]["new_score_fields"]+=len(missing)
            for key in missing:missing_score_fields[key]+=1
        else:
            score["all_score_values_already_present"]+=1
        score["already_equal_score_cells"]+=equals
        for key in vals:
            if key not in missing:already_score_fields[key]+=1

    # Compare already published market/research sidecars, never infer quote timestamps.
    side=Counter()
    market_files=sorted(market.glob("market-sidecar-*.jsonl.gz"))
    for p in market_files:
        assert assets[p.name]["digest"]=="sha256:"+dump_hash(p)
        with gzip.open(p,"rt",encoding="utf-8") as f:
            for line in f:
                if not line.strip():continue
                row=json.loads(line)
                side["published_market_records"]+=1
                mid=str(row.get("match_id") or "")
                if mid not in matches: # relevant exact-ID subset; not a global market coverage assessment
                    side["not_in_uploaded_match_cohort"]+=1
                    continue
                side["in_uploaded_match_cohort"]+=1
                marketinfo=row.get("historical_market") or {}
                if isinstance(marketinfo,dict):
                    side["with_market_object"]+=1
                    if "unspecified" in cleanstr(marketinfo.get("price_kind")):
                        side["no_verified_quote_time"]+=1

    # Only count safe same-identity anchors in published canonical sidecar,
    # no identity merge or player property writes.
    ident=Counter()
    canonical_player_ids={m[key] for m in matches.values() for key in ("player1_id","player2_id")}
    for p in sorted((source/"research/player_identity").glob("wikidata-canonical-links.jsonl.gz")):
        with gzip.open(p,"rt",encoding="utf-8") as f:
            for line in f:
                if not line.strip():continue
                r=json.loads(line)
                ident["canonical_identity_links_source"]+=1
                if str(r.get("player_id")) in canonical_player_ids:
                    ident["player_ids_in_uploaded_cohort"]+=1
                    if r.get("birth_dates"):ident["cohort_players_with_birth_dates"]+=1
                    if r.get("country_alpha3"):ident["cohort_players_with_country"]+=1
                    if r.get("hand_qids"):ident["cohort_players_with_handedness_identifiers"]+=1
    return {
        "schema":1,"status":"read_only_current_source_to_cdb_comparison",
        "sources":{"uploaded_matches":len(original),"source_sha256":raw_sha,"private_repo_commit":__import__("subprocess").check_output(["git","-C",str(source),"rev-parse","HEAD"],text=True).strip()},
        "canonical":{"year_partitions":len(per_year),"rows":sum(per_year.values()),"exact_id_matched":matched_ids},
        "core_observation_comparison":dict(core),
        "core_missing_cells_by_field":dict(missing_core_fields),
        "completed_match_score_comparison":dict(score),
        "score_missing_cells_by_field":dict(missing_score_fields),
        "score_conflicting_cells_by_field":dict(conflict_score_fields),
        "by_year":{str(y):dict(x) for y,x in sorted(annual.items())},
        "market_sidecar_overlap_in_uploaded_cohort":dict(side),
        "historical_player_identity_overlap_in_uploaded_cohort":dict(ident),
        "safety":{"no_cdb_writes":True,"no_model_training":True,"no_provider_requests":True,
                  "actual_write_authorized":False,
                  "score_candidates_read_only":True,
                  "require_independent_score_source_corroboration_and_fresh_sha_before_writer":True}
    }

def main():
    parser=argparse.ArgumentParser()
    for k in ("history","release-json","uploaded","market","source","output"):
        parser.add_argument("--"+k,required=True,type=Path)
    args=parser.parse_args()
    d=audit(args.history,json.loads(args.release_json.read_text()),
            args.uploaded,args.market,args.source)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print("BLINQ_ACTUAL_SOURCE_TO_CDB_FIELD_GAPS",json.dumps({k:v for k,v in d.items() if k not in ("sources","by_year")},sort_keys=True))
    print("BLINQ_GAP_BY_YEAR",json.dumps(d["by_year"],sort_keys=True))
if __name__=="__main__":main()
