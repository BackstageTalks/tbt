"""Audit pinned Sackmann WTA weekly rankings against canonical BlinQ history."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.wta_rank_history import WTARankHistory


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--history-dir",required=True)
    ap.add_argument("--players-csv",required=True)
    ap.add_argument("--ranking-csv",action="append",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    matches,safety=sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical identity quarantine is non-empty")
    history=WTARankHistory.from_sackmann(args.players_csv,args.ranking_csv)
    counts=Counter()
    samples=[]
    for m in matches:
        if str(m.tour or "").lower()!="wta":
            continue
        counts["canonical_wta_matches"]+=1
        day=m.scheduled_at.date()
        p1=history._snapshot(m.player1_name,day)
        p2=history._snapshot(m.player2_name,day)
        if p1 is not None:
            counts["player1_linked"]+=1
        if p2 is not None:
            counts["player2_linked"]+=1
        if p1 is None or p2 is None:
            counts["missing_one_or_both"]+=1
            if len(samples)<100:
                samples.append({
                    "match_id":str(m.match_id),
                    "scheduled_at":m.scheduled_at.isoformat(),
                    "player1":m.player1_name,
                    "player2":m.player2_name,
                    "player1_linked":p1 is not None,
                    "player2_linked":p2 is not None,
                })
            continue
        counts["linked_both"]+=1
        features=history.features_for_match(m)
        if features["wta_hist_momentum_4w_known_both"]>0:
            counts["momentum_4w_both"]+=1
        if features["wta_hist_momentum_12w_known_both"]>0:
            counts["momentum_12w_both"]+=1

        for existing,incoming in ((m.player1_rank,p1["rank"]),(m.player2_rank,p2["rank"])):
            if existing is None:
                continue
            counts["existing_rank_values"]+=1
            diff=abs(int(existing)-int(incoming))
            if diff==0:
                counts["existing_exact"]+=1
            if diff<=2:
                counts["existing_within2"]+=1
            if diff<=5:
                counts["existing_within5"]+=1

    total=counts["canonical_wta_matches"]
    linked=counts["linked_both"]
    existing=counts["existing_rank_values"]
    report={
        "schema":1,
        "source":"Aneeshers/tennis-sackmann-archive WTA (Jeff Sackmann mirror)",
        "source_commit":"83733587353df8a41f2fd4f516147d5aa83f5a8d",
        "license":"CC BY-NC-SA 4.0",
        "counts":dict(counts),
        "match_coverage_both":linked/total if total else 0.0,
        "momentum_4w_coverage":counts["momentum_4w_both"]/total if total else 0.0,
        "momentum_12w_coverage":counts["momentum_12w_both"]/total if total else 0.0,
        "existing_rank_exact_rate":counts["existing_exact"]/existing if existing else 0.0,
        "existing_rank_within2_rate":counts["existing_within2"]/existing if existing else 0.0,
        "existing_rank_within5_rate":counts["existing_within5"]/existing if existing else 0.0,
        "rapidapi_requests":0,
        "production_mutated":False,
        "missing_samples":samples,
    }
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
