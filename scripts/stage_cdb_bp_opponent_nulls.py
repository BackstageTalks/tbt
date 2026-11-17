#!/usr/bin/env python3
"""Build a PRIVATE read-only stage of exact opponent BP rate NULL complements.

Reuses the existing canonical importer; this module contains NO writer.
The current canonical identity and all original source stats are snapshotted,
and 0/100%-boundary or contradictory rates are never automatically staged.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from audit_cdb_bp_opponent_nulls import PAIRS, classify
from import_offline_linked_serve_return import _signature
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import select_exact_provider_quarantine


def _sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def stage(root, destination, expected_manifest, start_year, end_year):
    root, destination=Path(root),Path(destination)
    actual=_sha(root/"_tbt_bundle_manifest.json")
    if actual!=expected_manifest:
        raise ValueError("Current CDB bundle manifest changed since independent audit")
    years=json.loads((root/"history_manifest.json").read_text())["years"]
    if not all(str(y) in years for y in range(start_year,end_year+1)):
        raise ValueError("Canonical year missing from history manifest")
    matches, safety, protected = select_exact_provider_quarantine(
        load_partitions(root),expected_rows=0,preserve_quarantined=True)
    if safety["quarantined_rows"]!=0 or len(matches)!=safety["input_rows"]:
        raise ValueError("Canonical collision or row loss: no BP stage")
    now=datetime.now(timezone.utc)
    destinations={k:source for save,ret in PAIRS for k,source in ((save,ret),(ret,save))}
    counts=Counter()
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        raise FileExistsError("Refuse to replace an earlier private BP stage")
    with destination.open("x",encoding="utf-8") as output:
        for m in matches:
            y=m.scheduled_at.astimezone(timezone.utc).year
            if not start_year<=y<=end_year or str(m.tour or "").lower() not in ("atp","wta"):
                continue
            counts["cdb_matches_examined"]+=1
            if (str(m.match_id) in protected or not m.is_completed or
                    str(m.status).lower() not in ("finished","completed","ended") or
                    m.scheduled_at>=now or
                    str(m.player1_id)==str(m.player2_id) or
                    str(m.winner_id) not in {str(m.player1_id),str(m.player2_id)}):
                counts["source_record_not_authoritative_completed"]+=1
                continue
            existing=m.stats
            outcome, additions, boundary=classify(existing)
            counts[outcome]+=1
            counts["boundary_pairs_to_review"]+=boundary
            if not additions:
                continue
            if any(existing.get(k) is not None for k in additions):
                raise ValueError("NULL-only candidate tried to replace an existing field")
            if not all(0.0 < float(existing[destinations[k]]) < 1.0 for k in additions):
                raise ValueError("Missing original observed opposite-player rate witness")
            original_digest=hashlib.sha256(json.dumps(
                existing,sort_keys=True,ensure_ascii=False,separators=(",",":"),
                allow_nan=False,default=str).encode("utf-8")).hexdigest()
            source_provenance=[{
                "source":"canonical_preexisting_bp_serve_save_return_conversion",
                "source_match_id":str(m.match_id),
                "observed_stat_field":destinations[k],
                "observed_rate":existing[destinations[k]],
                "derived_null_field":k,
                "canonical_prewrite_stats_sha256":original_digest,
                "proof":"same_bp_opportunity_saved_or_converted_exact_opponent_complement",
                "source_bundle_sha256":expected_manifest,
                "model_pit_policy":"post_match_completed_history_only",
            } for k in sorted(additions)]
            output.write(json.dumps({
                "schema":1, "match_id":str(m.match_id), "canonical":_signature(m),
                "incoming_stats":additions, "sources":source_provenance,
                "import_ready":True,
            },ensure_ascii=False,sort_keys=True)+"\n")
            counts["staged_matches"]+=1
            counts["staged_new_null_cells"]+=len(additions)
            for k in additions:
                counts["candidate_"+k]+=1
    report={
        "schema":1,"status":"PRIVATE_CDB_BP_COMPLEMENT_STAGE_READONLY",
        "source_bundle_manifest_sha256":expected_manifest,
        "scope_years":[start_year,end_year],
        "stage_sha256":_sha(destination),
        "stage_rows":counts["staged_matches"],
        "counts":dict(sorted(counts.items())),
        "production_mutated":False, "provider_requests":0,
        "native_dryrun_required":True, "write_authorized":False,
        "meaning":"Existing accepted canonical BP observation, not independent new provider data",
    }
    (destination.parent/"stage-report.json").write_text(
        json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("CDB_BP_PRIVATE_NULL_ONLY_STAGE",json.dumps({
        "matches":counts["staged_matches"],
        "new_null_cells":counts["staged_new_null_cells"],
        "years":[start_year,end_year],"source_bundle":expected_manifest
    },sort_keys=True),flush=True)
    return report


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--history-dir",required=True,type=Path)
    ap.add_argument("--stage-file",required=True,type=Path)
    ap.add_argument("--expected-manifest",required=True)
    ap.add_argument("--start-year",type=int,required=True)
    ap.add_argument("--end-year",type=int,required=True)
    a=ap.parse_args()
    if not 2016<=a.start_year<=a.end_year<=2026:
        ap.error("Only historical ATP/WTA seasons 2016–2026")
    if len(a.expected_manifest)!=64 or any(c not in "0123456789abcdef" for c in a.expected_manifest):
        ap.error("Invalid pinned original CDB manifest SHA256")
    stage(a.history_dir,a.stage_file,a.expected_manifest,a.start_year,a.end_year)


if __name__=="__main__":
    main()
