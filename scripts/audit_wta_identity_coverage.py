"""Measure WTA ranking-history coverage before and after stable-ID crosswalk."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.wta_rank_history import WTARankHistory


def measure(matches, history):
    c=Counter()
    unresolved=Counter()
    for m in matches:
        if str(m.tour or "").lower()!="wta":
            continue
        c["matches"]+=1
        day=m.scheduled_at.date()
        p1=history._snapshot(
            m.player1_name,day,player_id=getattr(m,"player1_id",None)
        )
        p2=history._snapshot(
            m.player2_name,day,player_id=getattr(m,"player2_id",None)
        )
        if p1 is not None:
            c["player1_linked"]+=1
        else:
            unresolved[(str(m.player1_id),str(m.player1_name))]+=1
        if p2 is not None:
            c["player2_linked"]+=1
        else:
            unresolved[(str(m.player2_id),str(m.player2_name))]+=1
        if p1 is None or p2 is None:
            c["missing_one_or_both"]+=1
            continue
        c["linked_both"]+=1
        f=history.features_for_match(m)
        if f["wta_hist_momentum_4w_known_both"]>0:
            c["momentum_4w_both"]+=1
        if f["wta_hist_momentum_12w_known_both"]>0:
            c["momentum_12w_both"]+=1
    total=c["matches"]
    return {
        "counts":dict(c),
        "both_coverage":c["linked_both"]/total if total else 0.0,
        "momentum_4w_coverage":c["momentum_4w_both"]/total if total else 0.0,
        "momentum_12w_coverage":c["momentum_12w_both"]/total if total else 0.0,
        "top_unresolved":[
            {"player_id":pid,"name":name,"match_sides":count}
            for (pid,name),count in unresolved.most_common(100)
        ],
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--history-dir",required=True)
    ap.add_argument("--players-csv",required=True)
    ap.add_argument("--ranking-csv",action="append",required=True)
    ap.add_argument("--crosswalk",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    matches,safety=sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical identity quarantine is non-empty")

    baseline=WTARankHistory.from_sackmann(args.players_csv,args.ranking_csv)
    resolved=WTARankHistory.from_sackmann(
        args.players_csv,args.ranking_csv,crosswalk_path=args.crosswalk
    )
    before=measure(matches,baseline)
    after=measure(matches,resolved)
    report={
        "schema":1,
        "before":before,
        "after":after,
        "delta":{
            "both_coverage":after["both_coverage"]-before["both_coverage"],
            "linked_both":after["counts"].get("linked_both",0)-before["counts"].get("linked_both",0),
            "momentum_4w":after["counts"].get("momentum_4w_both",0)-before["counts"].get("momentum_4w_both",0),
            "momentum_12w":after["counts"].get("momentum_12w_both",0)-before["counts"].get("momentum_12w_both",0),
        },
        "rapidapi_requests":0,
        "production_mutated":False,
    }
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
