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
from audit_top_reliability import analyze as top_analyze, download, model_freshness, summarize
from audit_loss_review import analyze_loss_review, extract_entries
from audit_frozen_721_segments import audit as frozen_shadow_audit

DATA_REPOSITORY = "BackstageTalks/tbt-data"
REQUIRED = ("tbt-predictions-v1", "tbt-model-production-v1",
            "tbt-data-v1", "blinq-frozen-721-private-shadow-v1")


def compare_published_to_market(entries):
    """Same-pick displayed BlinQ probability versus pre-issue two-way no-vig quote."""
    from math import log
    from collections import defaultdict
    from random import Random
    rows=[e for e in entries if e.get("implied_source")=="both_sides_no_vig"
          and e.get("probability") is not None
          and e.get("implied_probability") is not None]
    if not rows:
        return {"n":0,"status":"NO_VERIFIED_COMPARABLE_TWO_WAY_QUOTES"}
    def individual(e):
        y=int(e["correct"])
        p=max(1e-9,min(1-1e-9,e["probability"]))
        q=max(1e-9,min(1-1e-9,e["implied_probability"]))
        brier_p=(p-y)**2
        brier_m=(q-y)**2
        ll_p=-(y*log(p)+(1-y)*log(1-p))
        ll_m=-(y*log(q)+(1-y)*log(1-q))
        return brier_p,brier_m,ll_p,ll_m
    scores=[individual(e) for e in rows]
    n=len(scores)
    by_day=defaultdict(lambda:[0.,0.,0])
    for e,(bp,bm,lp,lm) in zip(rows,scores):
        group=by_day[e["betting_day"]]
        group[0]+=bp-bm
        group[1]+=lp-lm
        group[2]+=1
    ci=None
    blocks=list(by_day.values())
    if len(blocks)>=10:
        rng=Random(721)
        draws=[]
        for _ in range(1000):
            picked=[blocks[rng.randrange(len(blocks))] for j in range(len(blocks))]
            draws.append(sum(x[0] for x in picked)/sum(x[2] for x in picked))
        draws.sort()
        ci=[draws[24],draws[974]]
    return {"n":n,"source":"issued_pairwise_no_vig_not_retrospective_odds",
            "blinq_brier":sum(x[0] for x in scores)/n,
            "market_brier":sum(x[1] for x in scores)/n,
            "blinq_minus_market_brier":sum(x[0]-x[1] for x in scores)/n,
            "blinq_log_loss":sum(x[2] for x in scores)/n,
            "market_log_loss":sum(x[3] for x in scores)/n,
            "blinq_minus_market_log_loss":sum(x[2]-x[3] for x in scores)/n,
            "paired_brier_daily_block_ci95":ci,
            "calendar_days":len(blocks),
            "market_side_favored_n":sum(e["implied_probability"]>=.5 for e in rows),
            "not_a_prospective_new_selector":True}


def compact(top, losses, shadow, *, version_breakdown, ledger_sha, model_sha, history_sha, now):
    """Keep aggregate-only fields; never include private loss examples."""
    return {
        "schema": 1,
        "status": "READ_ONLY_CURRENT_CHAMPION_DIAGNOSIS",
        "generated_at_utc": now.isoformat(),
        "source_releases": list(REQUIRED),
        "source_sha256": {"issued_ledger": ledger_sha, "production_training_report": model_sha,
                          "history_manifest": history_sha},
        "production_model_freshness": top["production_model_vs_history"],
        "published_top_by_model_version": version_breakdown,
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
    # TOP probabilities and version must originate from the issued publication.
    issued, _, _, _ = extract_entries(ledger, now=now, window_days=args.top_days)
    top_issued = [e for e in issued if e["section"] == "top_daily"]
    current_version = shadow["production_version"]
    verifiable = [e for e in top_issued if e["model_version_source"] in
                  {"exact_at_issuance", "matching_original_event"}]
    current = [e for e in verifiable if e["model_version"] == current_version]
    current_exact = [e for e in current if e["model_version_source"] == "exact_at_issuance"]
    start_21 = now.timestamp() - 21*86400
    def recent21(entry):
        return datetime.fromisoformat(entry["scheduled_at"]).timestamp() >= start_21
    def groups(items, key):
        return {group:summarize([e for e in items if e[key]==group])
                for group in sorted({e[key] for e in items})}
    # Predeclared probability bands, not fitted or applied as live filters.
    def conf_band(p):
        if p is None: return "unknown"
        if p < .68: return "below_68"
        if p < .75: return "68_75"
        if p < .80: return "75_80"
        if p < .85: return "80_85"
        return "85_plus"
    def gap_band(v):
        if v is None: return "unknown"
        if v < 0: return "negative"
        if v < .05: return "00_05"
        if v < .10: return "05_10"
        if v < .15: return "10_15"
        return "15_plus"
    tagged_current=[dict(e, audit_confidence_band=conf_band(e.get("probability")),
                         audit_market_gap=gap_band(e.get("probability_market_gap"))) for e in current]
    def mean(values):
        good=[float(x) for x in values if x is not None]
        return sum(good)/len(good) if good else None
    version_breakdown = {
        "current_version":current_version,
        "settled_top_all_versions":len(top_issued),
        "settled_top_version_verifiable":len(verifiable),
        "settled_top_unverified_model_version":len(top_issued)-len(verifiable),
        "by_model_version":groups(verifiable, "model_version"),
        "current_45_days":summarize(current),
        "current_exact_issue_45_days":summarize(current_exact),
        "current_21_days":summarize([e for e in current if recent21(e)]),
        "current_by_competition":groups(current, "competition"),
        "current_by_confidence_band":groups(tagged_current, "audit_confidence_band"),
        "current_by_market_gap_band":groups(tagged_current, "audit_market_gap"),
        "current_model_vs_market":compare_published_to_market(current),
        "current_exact_issue_model_vs_market":compare_published_to_market(current_exact),
        "current_market_reference": {
            "n_with_implied":sum(e.get("implied_probability") is not None for e in current),
            "mean_implied_probability":mean([e.get("implied_probability") for e in current]),
            "mean_public_minus_implied":mean([e.get("probability_market_gap") for e in current]),
            "implied_basis_counts":{k:sum(e.get("implied_source")==k for e in current)
                                    for k in sorted({e.get("implied_source") for e in current})},
        },
        "current_by_model_version_source":groups(current, "model_version_source"),
    }
    report=compact(top,losses,shadow,version_breakdown=version_breakdown,now=now,
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
