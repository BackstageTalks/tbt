#!/usr/bin/env python3
"""Read-only inventory of ALL canonical match fields, nested stat keys and null gaps.

Measures current 78-year Parquet snapshots with exact Release+manifest SHA256.
Never guesses missing values, links sources, writes CDB, or calls tennis APIs.
"""
import argparse, collections, hashlib, json, math, re
from pathlib import Path
import pandas as pd

def missing(v):
    if v is None:
        return True
    if isinstance(v,str):
        return v.strip().lower() in ("","nan","none","null","unknown","n/a")
    try:
        return bool(pd.isna(v))
    except (TypeError,ValueError):
        return False

def digest(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda:f.read(4*1024*1024),b""):
            h.update(c)
    return h.hexdigest()

def inspect(data_dir,release,out):
    release_assets={a["name"]:a for a in release["assets"]}
    manifest=json.loads((data_dir/"history_manifest.json").read_text())
    years=manifest["years"]
    files=sorted(data_dir.glob("history-*.parquet"))
    if len(files)!=len(years) or len(files)<78:
        raise ValueError("CDB yearly files incomplete")
    top_present=collections.Counter()
    top_missing=collections.Counter()
    observed_stats=collections.Counter()
    null_stats=collections.Counter()
    invalid_stats=collections.Counter()
    per_tour=collections.defaultdict(lambda:{
        "matches":0,"stats_any":0,"stats_nonempty":0,"score_two_sets":0,
        "serve_return_both":0,"ace_df_both":0,"winner_known":0,
        "current_core_missing":collections.Counter()
    })
    by_year=[]
    rows=0
    wrong_year_rows=0
    target=("service_points_won","return_points_won","aces","double_faults",
            "first_serve_win","second_serve_win","first_return_win",
            "second_return_win","break_points_won")
    top_expected=("tour","scheduled_at","player1_id","player1_name",
                  "player2_id","player2_name","surface","tournament",
                  "tournament_id","tournament_level","round_name",
                  "player1_rank","player2_rank","winner_id","status",
                  "best_of","indoor","provider_context_json")
    all_columns=None
    for path in files:
        year=int(re.search(r"history-(\d{4})\.parquet",path.name).group(1))
        actual=digest(path)
        if release_assets[path.name].get("digest")!="sha256:"+actual:
            raise ValueError("Release SHA mismatch "+path.name)
        if years[str(year)].get("sha256")!=actual:
            raise ValueError("Manifest SHA mismatch "+path.name)
        df=pd.read_parquet(path)
        if all_columns is None:
            all_columns=sorted(df.columns.tolist())
        elif sorted(df.columns.tolist())!=all_columns:
            raise ValueError("Different Parquet schema in "+path.name)
        ystats=collections.Counter()
        ygroup=collections.Counter()
        for c in top_expected:
            if c not in df.columns:
                raise ValueError("Missing canonical expected column "+c)
            # Fast vectorized pandas nulls plus sentinel text
            s=df[c]
            null=s.isna()
            if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
                null=null|s.astype("string").str.strip().str.lower().isin(["","nan","none","null","unknown","n/a"]).fillna(False)
            n=int(null.sum())
            top_missing[c]+=n
            top_present[c]+=len(df)-n
            ygroup[c+"_missing"]=n
        tour=df["tour"].fillna("unknown").astype(str).str.lower()
        stats=df["stats_json"]
        rows+=len(df)
        for i,raw in enumerate(stats):
            t=tour.iloc[i]
            tstats=per_tour[t]
            tstats["matches"]+=1
            if not missing(df["winner_id"].iat[i]):
                tstats["winner_known"]+=1
            if not isinstance(raw,str) or not raw.strip():
                d={}
            else:
                try:d=json.loads(raw)
                except Exception as exc:
                    raise ValueError(f"Invalid stats JSON in {year}: {exc}")
                if not isinstance(d,dict):
                    raise ValueError(f"Non-object stats JSON in {year}")
            if d:
                ystats["with_stats"]+=1
                tstats["stats_any"]+=1
            nonempty={k:v for k,v in d.items() if not missing(v)}
            if nonempty:
                tstats["stats_nonempty"]+=1
            for k,v in d.items():
                if missing(v):
                    null_stats[k]+=1
                else:
                    observed_stats[k]+=1
                    if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(float(v)):
                        invalid_stats[k]+=1
            for field in target:
                for prefix in ("p1","p2"):
                    k=f"{prefix}_{field}"
                    if k not in nonempty:
                        tstats["current_core_missing"][k]+=1
            if all(x in nonempty for x in ("p1_service_points_won","p2_service_points_won","p1_return_points_won","p2_return_points_won")):
                tstats["serve_return_both"]+=1
                ystats["serve_return_both"]+=1
            if all(x in nonempty for x in ("p1_aces","p2_aces","p1_double_faults","p2_double_faults")):
                tstats["ace_df_both"]+=1
                ystats["ace_df_both"]+=1
            if all(x in nonempty for x in ("p1_first_set_won","p2_first_set_won","p1_second_set_won","p2_second_set_won")):
                tstats["score_two_sets"]+=1
                ystats["score_two_sets"]+=1
        by_year.append({"year":year,"matches":len(df),"any_nonempty_stats":ystats["with_stats"],
                        "serve_return_complete":ystats["serve_return_both"],
                        "ace_df_complete":ystats["ace_df_both"],
                        "two_set_outcome_complete":ystats["score_two_sets"],
                        "missing_top_level":ygroup,
                        "sha256":actual})
    all_stats=sorted(set(observed_stats)|set(null_stats))
    per_tour_export={k:{**{p:v for p,v in group.items() if p!="current_core_missing"},
                         "missing_core":dict(group["current_core_missing"])}
                     for k,group in per_tour.items()}
    stat_count=sorted([{
        "field":field,"observed_values":observed_stats[field],
        "explicit_null_values":null_stats[field],
        "missing_or_null_out_of_all_matches":rows-observed_stats[field],
        "coverage_pct":round(100*observed_stats[field]/rows,4),
        "invalid_non_numeric_present_values":invalid_stats[field]}
        for field in all_stats],key=lambda r:(-r["observed_values"],r["field"]))
    report={
      "schema":1,"status":"ALL_CURRENT_CANONICAL_COLUMNS_AND_STATS_ENUMERATED",
      "scope":"Every current tbt-data-v1 history-YYYY.parquet; all matches; full score/key inventory",
      "year_partitions":len(files),"canonical_match_rows":rows,
      "columns":all_columns,
      "top_level":[{"field":c,"present":top_present[c],"missing_or_unknown":top_missing[c],
                    "coverage_pct":round(100*top_present[c]/rows,4)} for c in top_expected],
      "observed_stat_field_count":len(all_stats),
      "observed_stats":stat_count,
      "per_tour":per_tour_export,
      "per_year":by_year,
      "interpretation":"Missing_or_null is absence within entire canonical population, not independently provable availability at upstream provider. Sparse raw stats from postmatch are NOT same-match prematch model features.",
      "model_train_or_promotion":False,
      "canonical_db_mutated":False,
      "tennis_provider_requests":0,
    }
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("ALL_CDB_ENRICHMENT_GAPS_AUDITED",json.dumps({
        "matches":rows,"years":len(files),"stats":len(all_stats),
        "top_level":report["top_level"],
        "top_stats":stat_count[:55],"by_tour":{k:{x:y for x,y in z.items() if x!="missing_core"} for k,z in per_tour_export.items()}
    },ensure_ascii=False))

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--years-dir",type=Path,required=True)
    p.add_argument("--release-json",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    inspect(a.years_dir,json.loads(a.release_json.read_text()),a.output)
