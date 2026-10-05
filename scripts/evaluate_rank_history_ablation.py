"""Chronological ablation for ATP+WTA ranking-history candidate features.

Research-only: trains a baseline and a rank-history candidate on the same
canonical history and compares the same chronological holdout. Never promotes
or writes a production model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.atp_rank_history import ATPRankHistory
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.wta_rank_history import WTARankHistory
from tbt.services.training import train_from_matches

METRICS=("accuracy","roc_auc","log_loss","brier_score","ece_10")


def _metric_block(report):
    holdout=report.get("holdout") or {}
    return {key:holdout.get(key) for key in METRICS}


def _tour_block(report):
    return ((report.get("subgroups") or {}).get("tour") or {})


def _delta(candidate, baseline):
    out={}
    for key in METRICS:
        c=candidate.get(key)
        b=baseline.get(key)
        out[key]=None if c is None or b is None else float(c)-float(b)
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--history-dir",required=True)
    ap.add_argument("--atp-sqlite",required=True)
    ap.add_argument("--wta-players",required=True)
    ap.add_argument("--wta-ranking-csv",action="append",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    matches,safety=sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical identity quarantine is non-empty")

    atp=ATPRankHistory.from_sqlite(args.atp_sqlite)
    wta=WTARankHistory.from_sackmann(args.wta_players,args.wta_ranking_csv)

    baseline=train_from_matches(matches)
    candidate=train_from_matches(
        matches,
        atp_rank_history=atp,
        wta_rank_history=wta,
    )

    baseline_metrics=_metric_block(baseline.report)
    candidate_metrics=_metric_block(candidate.report)
    report={
        "schema":1,
        "production_mutated":False,
        "rapidapi_requests":0,
        "matches":len(matches),
        "baseline":baseline_metrics,
        "candidate":candidate_metrics,
        "delta_candidate_minus_baseline":_delta(candidate_metrics,baseline_metrics),
        "baseline_tour":_tour_block(baseline.report),
        "candidate_tour":_tour_block(candidate.report),
        "candidate_rank_history":{
            "atp":candidate.report.get("atp_rank_history"),
            "wta":candidate.report.get("wta_rank_history"),
        },
        "interpretation":{
            "higher_is_better":["accuracy","roc_auc"],
            "lower_is_better":["log_loss","brier_score","ece_10"],
            "promotion_attempted":False,
        },
    }
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    print(json.dumps(report,indent=2,default=str))


if __name__=="__main__":
    main()
