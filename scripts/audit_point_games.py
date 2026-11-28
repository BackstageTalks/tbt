"""Offline score audit, training-only calibration and paired games evaluation."""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

from evaluate_point_v2 import (CANDIDATE_SHA, competition, fit, fixture, format_for,
                              games_values, read_history, score_values, stats_surface_key)
from evaluate_point_model import reliability
from tbt.models.point_anchor import anchored_rates, calibrated_mean
from tbt.models.point_model import PointHistory
from tbt.models.point_rules import calibration_level, rules_for, score_audit, STANDARD
from tbt.models.point_simulation import simulate


def run(history_dir, candidate, previous, output):
    if hashlib.sha256(candidate.read_bytes()).hexdigest() != CANDIDATE_SHA:
        raise ValueError("Unexpected candidate export")
    if hashlib.sha256((history_dir/"history_manifest.json").read_bytes()).hexdigest() != "abdcbb7770ba6495ac9636bffc12345d0a56339a43e68a5c659f96cfab3aeb99":
        raise ValueError("Unexpected frozen history")
    records = read_history(history_dir, range(2023,2027))
    with candidate.open(encoding="utf-8") as src:
        rows = {r["match_id"]:r for r in csv.DictReader(src)}
    cohort = sorted((m for m in records if m.match_id in rows), key=lambda m:(m.scheduled_at,m.match_id))
    if len(cohort)!=9623:
        raise ValueError("Incomplete cohort")
    counts, format_counts = Counter(), Counter()
    eligible = {}
    old_over = old_n = new_over = 0
    for m in cohort:
        best = format_for(fixture(m))[0]
        old = games_values(m, score_values(m,best))
        if old is not None:
            old_n += 1
            old_over += sum(old)>20.5
        rules = rules_for(m)
        reason,g = score_audit(m,best,rules)
        counts[reason]+=1
        if rules and rules.match_tiebreak:
            format_counts[f"match_tb/{reason}"]+=1
            if g:
                format_counts[f"match_tb/played_{int(m.stats['total_sets'])}_sets"]+=1
        if g:
            eligible[m.match_id]=g
            new_over+=sum(g)>20.5
    output.mkdir(parents=True,exist_ok=True)
    audit = dict(counts=counts,formats=format_counts,old_n=old_n,old_over=old_over,
                 clean_n=len(eligible),clean_over=new_over)
    (output/"audit.json").write_text(json.dumps(audit,indent=2))
    calibration = fit(records)
    (output/"point_calibration_v2.json").write_text(json.dumps(calibration,sort_keys=True,indent=2))
    old_offsets = json.loads(previous.read_bytes())["groups"]
    replay = PointHistory(records)
    groups = defaultdict(lambda:defaultdict(list))
    sums = defaultdict(lambda: [0,0.,0.,0.,0.])
    for m in cohort:
        if m.match_id not in eligible:
            continue
        g = eligible[m.match_id]
        row = rows[m.match_id]
        if m.player1_id != row["player1_id"]:
            m=m.swapped()
            g=g[::-1]
        if (m.player1_id,m.player2_id,m.winner_id)!=(row["player1_id"],row["player2_id"],row["winner_id"]):
            raise ValueError("Candidate identity mismatch")
        replay.advance(m.scheduled_at-timedelta(microseconds=1))
        card = replay.card(fixture(m),candidate=float(row["p"]),offsets=calibration["groups"])
        p = float(row["p"])
        rules = rules_for(m)
        level,surface=calibration_level(m),stats_surface_key(m.surface)
        old_level=competition(m)
        offset=old_offsets.get(f"{old_level}|{surface}",old_offsets.get(old_level,old_offsets["all"]))["offset"]
        mu=calibrated_mean(card["anchor"]["raw_service_mean"],offset)
        best,target=card["best_of"],card["deciding_tiebreak_to"]
        def prior_predictions(rule):
            target_for_rule = 7 if rules.match_tiebreak and rule == STANDARD else target
            pts=anchored_rates(mu,p,best,target_for_rule,rule)
            return simulate(*pts,best,target_for_rule,rule)
        old=prior_predictions(STANDARD)
        corrected=prior_predictions(rules) if rules!=STANDARD else old
        new=card["other_projections"]["value"]
        keys=("all",level,"surface/"+surface,"quality/"+card["data_quality"],
              "/".join((level,surface,card["data_quality"])))
        for key in keys:
            totals=sums[key]
            totals[0]+=1
            totals[1]+=sum(g)
            for j,proj in enumerate((old,corrected,new),2):
                totals[j]+=sum(k*v for k,v in proj["total_games"].items())
            for arm,proj in (("51",old),("format",corrected),("52",new)):
                for line,prob in proj["totals"].items():
                    over=sum(g)>float(line)
                    for side in ("over","under"):
                        groups[key][arm+"/"+side+"/"+line].append((prob[side],int(over==(side=="over"))))
                for line,probs in proj["handicap"].items():
                    for i,v in enumerate(probs):
                        groups[key][f"{arm}/handicap/P{i+1}/{line}"].append((v,int(g[i]-g[1-i]+float(line)>0)))
    metrics={}
    for k,markets in groups.items():
        metrics[k]={}
        for name,pairs in markets.items():
            bins=reliability(pairs)
            metrics[k][name]={"n":len(pairs),"ece":sum(b["n"]*abs(b["p"]-b["y"]) for b in bins)/len(pairs),
                "brier":sum((p-y)**2 for p,y in pairs)/len(pairs),"bins":bins}
    result={"audit":audit,"groups":metrics,"means":{k:[v[0],*[n/v[0] for n in v[1:]]] for k,v in sums.items()}}
    (output/"evaluation.json").write_text(json.dumps(result,allow_nan=False))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("history","candidate","out"):
        parser.add_argument("--"+name,required=True,type=Path)
    parser.add_argument("--previous",type=Path,default=Path(__file__).with_name("point_calibration_51.json"))
    args=parser.parse_args()
    run(args.history,args.candidate,args.previous,args.out)
