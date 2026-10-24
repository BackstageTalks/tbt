"""Read-only current champion weak-spot audit on genuinely issued predictions.

Reuses audited extraction code. Downloads private sources in an ephemeral runner
and writes ONLY aggregated counts and metrics; no raw ledger rows, player IDs,
selection examples or credentials are uploaded as an artifact.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from _bootstrap import ROOT
from release_store import gh
from audit_top_reliability import analyze as top_analyze, download, model_freshness
from audit_loss_review import analyze_loss_review
from audit_frozen_721_segments import audit as frozen_shadow_audit

DATA_REPOSITORY = "BackstageTalks/tbt-data"
REQUIRED = ("tbt-predictions-v1", "tbt-model-production-v1",
            "tbt-data-v1", "blinq-frozen-721-private-shadow-v1")


def compact(top, losses, shadow, *, ledger_sha, model_sha, history_sha, now):
    """Keep aggregate-only fields; never include private loss examples."""
    return {
        "schema": 1,
        "status": "READ_ONLY_CURRENT_CHAMPION_DIAGNOSIS",
        "generated_at_utc": now.isoformat(),
        "source_releases": list(REQUIRED),
        "source_sha256": {"issued_ledger": ledger_sha, "production_training_report": model_sha,
                          "history_manifest": history_sha},
        "production_model_freshness": top["production_model_vs_history"],
        "published_top": {
            "window_days": top["window_days"],
            "overall": top["overall"],
            "diagnostics": top["diagnostics"],
            "coverage": {k: v for k, v in top["coverage"].items()
                         if k != "betting_day_counts"},
            "by_competition": top["subgroups"].get("competition", {}),
            "by_confidence": top["subgroups"].get("confidence_band", {}),
            "by_rank": top["subgroups"].get("ranking_1000", {}),
            "by_surface_evidence": top["subgroups"].get("surface_evidence", {}),
            "by_rank_surface": top["subgroups"].get("rank_and_surface", {}),
            "by_stats": top["subgroups"].get("stats", {}),
        },
        "published_top_value_losses": {
            "window_days": losses["window_days"],
            "overall": losses["overall"],
            "by_section": losses["by_section"],
            "by_competition": losses["by_competition"],
            "shadow_filters": losses["rule_simulations"],
            "diagnostics": losses["diagnostics"],
            "discarded_individual_loss_examples": len(losses.get("losses", [])),
        },
        "prospective_champion_vs_frozen_721": {
            k: v for k, v in shadow.items()
            if k not in ("eligible_rows_by_utc_day",)
        },
        "provider_requests": 0,
        "production_mutated": False,
        "model_fitting_performed": False,
        "automatic_promotion": False,
        "limitations": [
            "Historical champion training holdout and actual issued picks have different cohorts.",
            "Only actually published pre-start TOP/value and verified settled forecasts count.",
            "A production-level prediction may have no corresponding issued market selection.",
            "No retrospective candidate filter is validated prospectively by this diagnostic.",
            "Small competition and confidence bins may be noisy; inspect n and uncertainty.",
            "No source-level player or match information appears in the uploaded summary."
        ]
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--top-days",type=int,default=45)
    parser.add_argument("--loss-days",type=int,default=21)
    args=parser.parse_args()
    if args.top_days <= 0 or args.loss_days <= 0:
        parser.error("Audit window must be positive")
    for tag in REQUIRED:
        gh("api",f"repos/{DATA_REPOSITORY}/releases/tags/{tag}")
    cache = ROOT / ".cache/tbt/champion-weakness-ephemeral"
    ledger=download(DATA_REPOSITORY,"tbt-predictions-v1","ledger.json",cache/"predictions")
    training=download(DATA_REPOSITORY,"tbt-model-production-v1","training_report.json",cache/"champion")
    history=download(DATA_REPOSITORY,"tbt-data-v1","history_manifest.json",cache/"history")
    if not isinstance(ledger,list) or not isinstance(training,dict) or not isinstance(history,dict):
        raise ValueError("Private release shape failure")
    now=datetime.now(timezone.utc)
    top=top_analyze(ledger,now=now,window_days=args.top_days)
    top["production_model_vs_history"]=model_freshness(training,history)
    losses=analyze_loss_review(ledger,now=now,window_days=args.loss_days)
    shadow=frozen_shadow_audit(DATA_REPOSITORY)
    report=compact(top,losses,shadow,now=now,
        ledger_sha=sha256((cache/"predictions/ledger.json").read_bytes()).hexdigest(),
        model_sha=sha256((cache/"champion/training_report.json").read_bytes()).hexdigest(),
        history_sha=sha256((cache/"history/history_manifest.json").read_bytes()).hexdigest())
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False),encoding="utf-8")
    print(json.dumps({
        "status":report["status"],
        "prospective_settled":report["prospective_champion_vs_frozen_721"]["eligible_settled"],
        "published_top_settled":report["published_top"]["overall"]["settled"],
        "published_loss_review_settled":report["published_top_value_losses"]["overall"]["settled"],
        "production_mutated":False,"provider_requests":0,
        "path":str(args.out),
    },sort_keys=True))


if __name__=="__main__":
    main()
