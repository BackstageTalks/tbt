"""Read-only TOP direction audit of frozen whole-offer snapshots.

No model fit, market API, CDB mutation or publication. Missing historical policy
fields are reported, never reconstructed as if they were frozen before kickoff.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

from replay_selection_reliability import anchors, canonical_index, dt, load_snapshots, prepare


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ledger_outcome(source, row):
    """Exact event + unordered player IDs + schedule, with explicit void handling."""
    if not row or str(row.get("event_id")) != str(source.get("event_id")):
        return None
    ids = {str((source.get(side) or {}).get("id") or "") for side in ("player1", "player2")}
    other = {str((row.get(side) or {}).get("id") or "") for side in ("player1", "player2")}
    if len(ids) != 2 or "" in ids or ids != other:
        return None
    result = row.get("result") or {}
    if result.get("status") == "void":
        return None
    winner = str(result.get("winner_id") or "")
    try:
        schedule_ok = abs((dt(source["scheduled_at"]) - dt(result.get("scheduled_at") or row["scheduled_at"])).total_seconds()) <= 86400
    except (ValueError, KeyError):
        return None
    if not schedule_ok or winner not in ids:
        return None
    return winner


def summarize(rows):
    done = [r for r in rows if type(r.get("correct")) is bool]
    n = len(done); wins = sum(r["correct"] for r in done)
    p = wins/n if n else None
    interval = None
    if n:
        z = 1.959963984540054
        den = 1+z*z/n
        center = (p+z*z/(2*n))/den
        half = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
        interval = [center-half,center+half]
    priced = [r for r in done if r["quote_ok"]]
    profit = sum(r["odds"]-1 if r["correct"] else -1 for r in priced)
    return {"candidates":len(rows),"settled":n,"wins":wins,"losses":n-wins,
            "hit_rate":p,"wilson_95":interval,"priced_settled":len(priced),
            "profit_units":round(profit,6),"roi":profit/len(priced) if priced else None,
            "mean_public_probability":sum(r["public"] for r in done)/n if n else None,
            "brier":sum((r["public"]-int(r["correct"]))**2 for r in done)/n if n else None}


def close_market(row):
    market = row["two_way"]
    try:
        a,b = float(market["player1_odds"]),float(market["player2_odds"])
        return math.isfinite(a+b) and a>1 and b>1 and abs(a-b)/((a+b)/2) <= .15+1e-12
    except (KeyError,TypeError,ValueError):
        return False


def analyze(snapshots, matches, ledger):
    index=canonical_index(matches)
    li={}; duplicates=set()
    for row in ledger:
        event=str(row.get("event_id") or "")
        if event in li: duplicates.add(event)
        li[event]=row
    diag=Counter(); records=[]; seen=set()
    daily=anchors(snapshots)
    for day,snapshot in sorted(daily.items()):
        for source in snapshot["rows"]:
            record=prepare(source,dt(snapshot["generated_at"]),day,index,diag)
            if record is None:continue
            event=record["event"]
            if event in seen:
                diag["repeated_event_excluded"]+=1;continue
            seen.add(event)
            ledger_row=li.get(event) if event not in duplicates else None
            observed=ledger_outcome(source,ledger_row)
            if observed is not None:
                result=observed==str(source["winner_id"])
                if record["correct"] is not None and result!=record["correct"]:
                    diag["canonical_ledger_conflict"]+=1;record["correct"]=None
                elif record["correct"] is None and index.get(event) is None:
                    # Only fill absent canonical events; never override an
                    # existing canonical identity/date/termination rejection.
                    record["correct"]=result
                    record["level"]=str(ledger_row.get("competition") or "unknown")
                    diag["outcomes_added_from_exact_ledger"]+=1
            record["strict_policy_fields_present"]=bool(source.get("competition") and source.get("created_at"))
            record["source"]=source
            record["snapshot_at"]=snapshot["generated_at"]
            records.append(record)
    cohorts={"all_versions":records,
             "current_721":[r for r in records if r["model"].startswith("v7.2.1-")]}
    output={}
    for name,rows in cohorts.items():
        groups={}
        for level in sorted({r["level"] for r in rows}):
            subset=[r for r in rows if r["level"]==level]
            groups[level]={"all_frozen_predictions":summarize(subset),
                "priced_odds_ge_150":summarize([r for r in subset if r["quote_ok"] and r["odds"]>=1.5]),
                "stored_top_candidates":summarize([r for r in subset if r["section"]=="top_daily"])}
        main=[r for r in rows if r["level"] in {"ATP","WTA"} and r["quote_ok"] and r["odds"]>=1.5
              and r["depth"]>=.8 and (r["min_surface"] or 0)>=5
              and not (r["odds"]>1.8 and close_market(r))]
        screens={str(floor):summarize([r for r in main if r["public"]>=floor]) for floor in (.70,.75,.80,.85,.90)}
        split={}
        for period,predicate in [("through_oct31",lambda r:r["day"]<"2026-11-01"),
                                 ("nov01_onward",lambda r:r["day"]>="2026-11-01")]:
            split[period]=summarize([r for r in main if predicate(r) and r["public"]>=.80])
        output[name]={"groups":groups,"main_tour_economic_screens_not_exact_policy_replay":screens,
                      "fixed80_descriptive_time_split_not_blind":split,
                      "priority70_capacity_screen_not_exact_replay":capacity_screen(rows)}
    return {"status":"DESCRIPTIVE_RESEARCH_NOT_PROVEN_PROFITABLE", "snapshots":len(snapshots),
            "anchored_days":len(daily),"first_day":min(daily),"last_day":max(daily),
            "unique_events":len(records),"settled":sum(r["correct"] is not None for r in records),
            "strict_policy_fields_present":sum(r["strict_policy_fields_present"] for r in records),
            "diagnostics":dict(diag),"cohorts":output,
            "limitations":["Earliest snapshot at/after 06:00 Bratislava per day, >=15 minutes before start; not all intraday offers.",
                "Historical category from exact canonical/ledger join is descriptive, not proof of prematch category provenance.",
                "Unmatched, void and inconsistent outcomes excluded; missing does not count as a loss.",
                "Stored selected_section means candidate assignment, not proof of published TOP.",
                "Threshold screens are exploratory; neither a blind test nor an exact replay of the new provenance gates.",
                "Profit uses observed snapshot prices and unit stakes, without fees or bookmaker-specific retirement rules."]}


def capacity_screen(records):
    """Descriptive supply estimate. Never pretend imputed fields were archived."""
    from tbt.services.market_selection import select_market_sections
    groups=defaultdict(list)
    for record in records:
        groups[record["day"]].append(record)
    selected_records=[];days=[];mix=Counter()
    for day,rows in sorted(groups.items()):
        inputs=[]
        for record in rows:
            if not record["quote_ok"]:continue
            source=record["source"];samples=source["samples"]
            inputs.append({**source,"competition":source.get("competition") or record["level"],
                "created_at":source.get("created_at") or record["snapshot_at"],
                "betting":{**source["betting"],"market":"match_winner",
                           "model_probability":record["raw"],"blinq_probability":record["public"]},
                "match_winner_market":source["two_way_market"],
                "quality":{side:{"matches":samples.get(side+"_matches"),
                                 "surface_matches":samples.get(side+"_surface_matches")}
                           for side in ("player1","player2")}})
        chosen=select_market_sections(inputs)["top_daily_picks"]
        by_id={r["event"]:r for r in rows}
        picks=[by_id[c["event_id"]] for c in chosen]
        selected_records.extend(picks);mix.update(r["level"] for r in picks)
        days.append({"day":day,"selected":len(picks),"settled":sum(r["correct"] is not None for r in picks)})
    return {"days":days,"days_with_three":sum(r["selected"]==3 for r in days),
            "mix":dict(mix),"metrics":summarize(selected_records),
            "not_exact_policy_replay":True,
            "surrogates":"Missing category uses canonical/ledger level; missing created_at uses archived snapshot existence as upper bound. No invented odds."}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshots",nargs="+",type=Path,required=True)
    ap.add_argument("--canonical",type=Path,required=True)
    ap.add_argument("--ledger",type=Path,required=True)
    ap.add_argument("--manifest",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding="utf-8"))
    for path in [*args.snapshots,args.ledger]:
        if sha(path)!=(manifest.get("files",{}).get(path.name) or {}).get("sha256"):
            raise ValueError("Bundle checksum mismatch: "+path.name)
    import pandas as pd
    frame=pd.read_parquet(args.canonical)
    report=analyze(load_snapshots(args.snapshots),frame.to_dict("records"),json.loads(args.ledger.read_text(encoding="utf-8")))
    report["inputs"]={p.name:{"sha256":sha(p),"bytes":p.stat().st_size} for p in [*args.snapshots,args.ledger,args.canonical,args.manifest]}
    report["canonical"]={"rows":len(frame),"first":str(frame.scheduled_at.min()),"last":str(frame.scheduled_at.max())}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("snapshots","anchored_days","unique_events","settled","strict_policy_fields_present","diagnostics")}))


if __name__=="__main__":main()
