"""Read-only same-slate replay for the production-shaped ranked TOP morning offer.

Measures daily TOP-1/3/5 positions inside ONE original TOP market, not new offers.
Never changes the immutable issued ledger, model, CDB or provider quota. The
replay only grades pre-start snapshots whose independent canonical outcome is
unambiguous and must not be sold as a prospective blind performance test.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from replay_selection_reliability import anchors, canonical_index, dt, load_snapshots, prepare, verify_pins
from tbt.services.market_selection import (
    TOP_MIN_COUNT, TOP_TARGET_COUNT, TOP_MIN_PROBABILITY, TOP_MIN_ODDS,
    TOP_BACKUP_MIN_DATA_DEPTH, TOP_BACKUP_MIN_SURFACE_MATCHES,
    TOP_MIN_DATA_DEPTH, TOP_MIN_SURFACE_MATCHES,
    _rank_full_slate_top,
)
from tbt.services.price_integrity import extreme_winner_price_inversion


def market_card(replayed, frozen):
    """Reconstruct only immutable pre-start selector features, without result."""
    market = frozen.get("two_way_market") if isinstance(frozen.get("two_way_market"), dict) else {}
    player1 = frozen.get("player1") if isinstance(frozen.get("player1"), dict) else {}
    player2 = frozen.get("player2") if isinstance(frozen.get("player2"), dict) else {}
    side = "player1" if str(frozen.get("winner_id")) == str(player1.get("id")) else "player2"
    odds = replayed.get("odds")
    fair = market.get(side + "_implied_probability")
    samples = frozen.get("samples") if isinstance(frozen.get("samples"), dict) else {}
    return {
        "event_id": replayed["event"],
        "probability": replayed["public"], "odds": odds,
        "fair_implied_probability": fair,
        "data_depth": replayed["depth"],
        "quality": {
            "player1": {"surface_matches": samples.get("player1_surface_matches"),
                        "matches": samples.get("player1_matches")},
            "player2": {"surface_matches": samples.get("player2_surface_matches"),
                        "matches": samples.get("player2_matches")},
        },
        "betting": {
            "selection_id": frozen.get("winner_id"),
            "market": "match_winner", "betting_day": replayed["day"],
        },
    }


def valid_market_candidate(r):
    if not r["quote_ok"] or r["odds"] is None or r["odds"] < TOP_MIN_ODDS:
        return False
    if r["public"] < TOP_MIN_PROBABILITY:
        return False
    if r["min_surface"] is None or r["min_surface"] < TOP_BACKUP_MIN_SURFACE_MATCHES:
        return False
    if r["depth"] < TOP_BACKUP_MIN_DATA_DEPTH:
        return False
    if extreme_winner_price_inversion(r["public"], r["odds"]):
        return False
    return not is_original_value(r)


def is_original_value(r):
    if not r["quote_ok"] or r["odds"] is None or r["odds"] < 1.80:
        return False
    if r["public"] < 0.65 or r["depth"] < 0.75 or r["min_surface"] is None or r["min_surface"] < 3:
        return False
    market = r["two_way"]
    try:
        x,y = float(market["player1_odds"]), float(market["player2_odds"])
    except (TypeError, KeyError, ValueError):
        return False
    return x > 1 and y > 1 and abs(x-y) / ((x+y)/2) <= .15+1e-12


def score(rows):
    graded = [r for r in rows if type(r.get("correct")) is bool]
    wins = sum(r["correct"] for r in graded)
    profit = sum(r["odds"]-1.0 if r["correct"] else -1.0 for r in graded)
    return {
        "candidates":len(rows), "settled":len(graded),
        "wins":wins, "losses":len(graded)-wins,
        "pending_or_unmatched":len(rows)-len(graded),
        "hit_rate":round(wins/len(graded),6) if graded else None,
        "hypothetical_profit_1u":round(profit,6),
        "hypothetical_roi":round(profit/len(graded),6) if graded else None,
    }


def compare_days(day_groups):
    """Already-independent-canonical records; selector gets only prestart card."""
    result = {}
    for model, days in sorted(day_groups.items()):
        cohorts=defaultdict(list)
        periods=defaultdict(lambda:defaultdict(list))
        report_days={}
        blockers=Counter()
        for day, rows in sorted(days.items()):
            old = [r for r in rows if r.get("section") == "top_daily" and r["quote_ok"]]
            core, backup=[],[]
            for r in rows:
                if not valid_market_candidate(r):
                    continue
                card=r["ranking_card"]
                if r["depth"] >= TOP_MIN_DATA_DEPTH and r["min_surface"] >= TOP_MIN_SURFACE_MATCHES:
                    core.append(card)
                else:
                    backup.append(card)
            selected, fallback_count, applied = _rank_full_slate_top(
                core, backup, target=TOP_TARGET_COUNT, minimum=TOP_MIN_COUNT,
            )
            by_event={r["event"]:r for r in rows}
            new=[by_event[c["event_id"]] for c in selected]
            old_ids={r["event"] for r in old}; new_ids={r["event"] for r in new}
            groups={
                "original_snapshot_top":old,
                "ranked_top1":new[:1],
                "ranked_top3":new[:3],
                "ranked_top5":new,
                "both": [r for r in new if r["event"] in old_ids],
                "new_only":[r for r in new if r["event"] not in old_ids],
                "old_only":[r for r in old if r["event"] not in new_ids],
            }
            report_days[day]={key:score(values) for key,values in groups.items()}
            report_days[day]["qualified_core"]=len(core)
            report_days[day]["qualified_backup"]=len(backup)
            report_days[day]["used_backup"]=fallback_count
            report_days[day]["shortfall"]=applied["shortfall"]
            report_days[day]["no_valid_price"]=sum(not r["quote_ok"] for r in rows)
            if applied["shortfall"]:
                blockers["days_below_3"]+=1
                if not core and not backup:
                    blockers["no_quality_qualified_market_after_value"]+=1
            for label,values in groups.items():
                cohorts[label].extend(values)
                periods["development_before_2026_11_01" if day < "2026-11-01" else "later_from_2026_11_01"][label].extend(values)
        result[model]={
            "days":report_days,
            "totals":{key:score(values) for key,values in cohorts.items()},
            "chronological_descriptive":{period:{key:score(values) for key,values in vals.items()} for period,vals in sorted(periods.items())},
            "blockers":dict(blockers),
            "days_count":len(days),
            "warning":"Frozen candidate assignment is NOT actual public issuance. 7.2.1 vs old TOP is an unequal-denominator descriptive comparison, not proof of improved future ROI.",
        }
    return {"status":"READ_ONLY_MORNING_TOP_RANK_SHADOW_NOT_DEPLOYMENT_CERTIFICATE",
            "market_output":"top_daily_picks_only", "no_new_offer":True,
            "provider_requests":0, "cdb_writes":0, "production_changes":0,
            "models":result}


def evaluate(snapshots, canonical):
    index=canonical_index(canonical)
    diagnostic=Counter()
    seen=set()
    by_model=defaultdict(lambda:defaultdict(list))
    for day,snap in sorted(anchors(snapshots).items()):
        moment=dt(snap["generated_at"])
        for frozen in snap.get("rows",[]):
            r=prepare(frozen,moment,day,index,diagnostic)
            if r is None:
                continue
            identity=(r["model"],r["event"])
            if identity in seen:
                diagnostic["duplicate_model_event"]+=1
                continue
            seen.add(identity)
            r["ranking_card"]=market_card(r,frozen)
            by_model[r["model"]][day].append(r)
    out=compare_days(by_model)
    out["diagnostics"]=dict(sorted(diagnostic.items()))
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots",nargs="+",type=Path,required=True)
    parser.add_argument("--canonical",type=Path,required=True)
    parser.add_argument("--prediction-before",type=Path,required=True)
    parser.add_argument("--prediction-after",type=Path,required=True)
    parser.add_argument("--history-before",type=Path,required=True)
    parser.add_argument("--history-after",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    import pandas as pd
    snapshot_files=list(args.snapshots)
    verify_pins(args.prediction_before,args.prediction_after,[p.name for p in snapshot_files],snapshot_files[0].parent,require_manifest=True)
    verify_pins(args.history_before,args.history_after,[args.canonical.name],args.canonical.parent,require_manifest=True)
    columns=["match_id","player1_id","player2_id","winner_id","status","scheduled_at","tour","provider_context_json"]
    canonical=pd.read_parquet(args.canonical,columns=columns).to_dict("records")
    out=evaluate(load_snapshots(snapshot_files),canonical)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(out,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"status":out["status"],"models":{
        k:{"days":v["days_count"],"original":v["totals"].get("original_snapshot_top"),
           "ranked_top3":v["totals"].get("ranked_top3"),"ranked_top5":v["totals"].get("ranked_top5"),
           "blockers":v["blockers"]}
        for k,v in out["models"].items()
    }},ensure_ascii=False))


if __name__=="__main__":
    main()
