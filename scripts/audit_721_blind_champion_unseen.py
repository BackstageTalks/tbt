"""Blind 7.2.1 vs incumbent audit: only originally issued forecasts count.

Reconcile the 9,796 champion-unseen CDB rows with the frozen candidate's
own consumed selection holdout. Never call rescoring a prospective blind test.
No model retraining, API calls, CDB mutation, app deployment or release writes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone, date
import hashlib
import json
from pathlib import Path

from _bootstrap import ROOT
from audit_frozen_721_unseen_overlap import audit as overlap_audit, _load_history
from audit_frozen_721_segments import (
    audit as segment_audit, _time, _paired_result, MIN_CAPTURE_LEAD_SECONDS,
)
from frozen_721_shadow_capture import LEDGER_ASSET
from tbt.services.frozen_721_research import validate_frozen_evidence, exclude_repeated_events
from tbt.services.data_quality import audit_history

REPO="BackstageTalks/tbt-data"


def build_result(overlap: dict, segment: dict, shadow: dict,
                 canonical_matches, as_of: datetime) -> dict:
    """Cross-match actual pre-issued pairs to exact canonical match IDs."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of needs an explicit timezone")
    today = as_of.astimezone(timezone.utc).date()
    cutoff_champion = date.fromisoformat(overlap["champion_cutoff_utc_day"])
    cutoff_721 = date.fromisoformat(overlap["candidate_consumed_cutoff_utc_day"])
    accepted, _ = audit_history(canonical_matches)
    champion_ids = set()
    fresh_ids = set()
    for x in accepted:
        day = x.scheduled_at.astimezone(timezone.utc).date()
        if cutoff_champion < day < today:
            key = str(x.match_id)
            if key in champion_ids:
                raise ValueError("duplicate_canonical_unseen_match")
            champion_ids.add(key)
            if day > cutoff_721:
                fresh_ids.add(key)
    if len(champion_ids) != overlap["champion_unseen_reported"]:
        raise ValueError("read_back_cohort_disagrees")
    if len(fresh_ids) != overlap["strictly_after_all_frozen_721_consumption"]["rows"]:
        raise ValueError("fresh_cohort_disagrees")
    if not segment["candidate_version"] == overlap["candidate"]["frozen_candidate_version"]:
        raise ValueError("candidate_version_mismatch")
    if not segment["production_version"] == overlap["candidate"]["production_version"]:
        raise ValueError("champion_version_mismatch")
    if not segment["candidate_model_sha256"] == overlap["candidate_sha256"]:
        raise ValueError("model_sha_mismatch")

    source = shadow["source"]
    rows, prior_counts = validate_frozen_evidence(shadow, production_version=source["production_version"])
    rows = exclude_repeated_events(rows)
    rows, dedupe_counts = validate_frozen_evidence({**shadow,"rows":rows}, production_version=source["production_version"])
    if prior_counts["settled"] != dedupe_counts["settled"]:
        raise ValueError("settled_rows_were_deduplicated")
    accepted_pairs=[]
    old_pairs=[]
    near_start=0
    ineligible=0
    for row in rows:
        if row.get("status")!="settled":continue
        match_id=str(row["match_id"])
        if match_id not in champion_ids:
            ineligible+=1
            continue
        elapsed=(_time(row["scheduled_at"])-_time(row["captured_at"])).total_seconds()
        if elapsed < MIN_CAPTURE_LEAD_SECONDS:
            near_start+=1
            continue
        if match_id in fresh_ids:
            accepted_pairs.append(row)
        else:
            old_pairs.append(row)
    def unique(items):
        event_keys=[str(r.get("event_id") or r["match_id"]) for r in items]
        if len(set(event_keys))!=len(event_keys):
            raise ValueError("duplicated_issued_event")
    unique(accepted_pairs)
    unique(old_pairs)
    def by_tour(items):
        return {t:_paired_result([r for r in items if str(r["tour"]).upper()==t])
                for t in ("ATP","WTA")}
    def confidence(items,side):
        fld="production_player1_probability" if side=="champion" else "challenger_player1_probability"
        return [r for r in items if max(float(r[fld]),1-float(r[fld]))>=.8]
    winner_disagreement=_paired_result(accepted_pairs)["paired_diagnostics"] if accepted_pairs else {}
    return {
        "schema":1,
        "status":"ISSUED_PAIRED_BLIND_COMPARISON" if accepted_pairs else "NO_FRESH_ISSUED_PAIRS",
        "source_mode":"original_pre_start_shadow_predictions_only",
        "as_of_utc":as_of.isoformat(),
        "model_version":{"champion":segment["production_version"],"candidate_721":segment["candidate_version"]},
        "model_sha256":{"candidate_721":segment["candidate_model_sha256"]},
        "time_guard_seconds":MIN_CAPTURE_LEAD_SECONDS,
        "cohort":{
            "champion_unseen_original":len(champion_ids),
            "consumed_by_frozen_721_or_its_evaluation":len(champion_ids)-len(fresh_ids),
            "fresh_after_frozen_721_consumption":len(fresh_ids),
            "fresh_and_actually_issued_and_settled":len(accepted_pairs),
            "overlap_old_issued_and_settled_not_blind":len(old_pairs),
            "quarantined_near_start":near_start,
            "other_settled_outside_champion_9796_cohort":ineligible,
            "missing_fresh_original_pair":len(fresh_ids)-len(accepted_pairs)
        },
        "fresh_paired":_paired_result(accepted_pairs),
        "fresh_by_tour":by_tour(accepted_pairs),
        "fresh_champion_confidence_80":_paired_result(confidence(accepted_pairs,"champion")),
        "fresh_721_confidence_80":_paired_result(confidence(accepted_pairs,"721")),
        "fresh_utc_days":len({str(r["scheduled_at"])[:10] for r in accepted_pairs}),
        "all_issued_context":{"settled":segment["eligible_settled"],
                              "reported_accuracy_delta":segment["overall"]["candidate_minus_champion"]["accuracy"]},
        "paired_winner_disagreement":winner_disagreement,
        "quality":{
            "no_future_prediction_reconstruction":True,
            "candidate_cutoff_day_respected":True,
            "original_issued_pair_required":True,
            "canonical_match_id_required":True,
            "exact_model_sha_verified":True,
            "unknown_or_uncaptured_matches_not_assigned_predictions":True,
        },
        "no_retraining":True,"no_model_promotion":True,"production_mutated":False,
        "provider_requests":0,
        "interpretation":("Only fresh, genuinely issued paired predictions are blind. "
                          "Previously consumed historical rows are excluded even if the champion never trained on them. "
                          "Small cohorts and only two UTC dates are exploratory, not promotion evidence.")
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",required=True,type=Path)
    args=parser.parse_args()
    now=datetime.now(timezone.utc)
    overlap=overlap_audit(repo=REPO,as_of=now)
    segment=segment_audit(REPO)
    shadow_path=ROOT/".cache/tbt/frozen-721-segment-audit"/LEDGER_ASSET
    shadow=json.loads(shadow_path.read_text(encoding="utf-8"))
    canonical=_load_history(REPO)
    result=build_result(overlap,segment,shadow,canonical,now)
    result["private_shadow_sha256"]=hashlib.sha256(shadow_path.read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    # No player IDs, match IDs, individual predictions or credentials leave runner.
    print(json.dumps({"status":result["status"],
                      "unseen":result["cohort"]["champion_unseen_original"],
                      "fresh":result["cohort"]["fresh_after_frozen_721_consumption"],
                      "issued_settled":result["cohort"]["fresh_and_actually_issued_and_settled"],
                      "report":str(args.out),"provider_requests":0,"production_mutated":False},
                      sort_keys=True))


if __name__=="__main__":
    main()
