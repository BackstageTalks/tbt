#!/usr/bin/env python3
"""Read-only current CDB Serve/Return coverage audit; never writes canonical."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

RATE_NAMES = (
    "first_serve_win", "second_serve_win", "service_points_won",
    "return_points_won", "break_point_serve_win", "break_point_return_win",
)
COUNT_NAMES = ("aces", "double_faults")
RECOVERY_PAIRS = tuple((f"{a}_{s}",f"{b}_{t}")
    for a,b in (("p1","p2"),("p2","p1"))
    for s,t in (("first_serve_win","first_return_win"),
                ("second_serve_win","second_return_win"),
                ("service_points_won","return_points_won")))


def valid_rate(value):
    import math
    return (isinstance(value,(int,float)) and not isinstance(value,bool)
            and math.isfinite(value) and 0 <= value <= 1)


def json_object(value):
    if isinstance(value, dict):
        return value
    if value is None or value == "":
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Invalid CDB JSON dictionary")
    return parsed


def profile(rows):
    counter = Counter()
    samples = {}
    for row in rows:
        counter["canonical_matches"] += 1
        mid = str(row["match_id"])
        if mid.startswith("hist-js:"):
            family = "hist_js"
        elif mid.startswith("hist-"):
            family = "other_historical"
        else:
            family = "provider_or_other"
        counter[f"matches_{family}"] += 1
        stats = json_object(row.get("stats_json"))
        context = json_object(row.get("provider_context_json"))
        provenance = context.get("_tbt_statistics")
        if isinstance(provenance, dict):
            counter["canonical_source_evidence_matches"] += 1
            source = str(provenance.get("source") or "")
            if source.startswith("jeff_sackmann_match_snapshot:"):
                counter["exact_sackmann_lineage_markers"] += 1
            if len(samples) < 8 and source:
                samples.setdefault(source[:120], 0)
                samples[source[:120]] += 1
        for side in ("p1", "p2"):
            for name in RATE_NAMES + COUNT_NAMES:
                key = f"{side}_{name}"
                value = stats.get(key)
                counter[f"non_null_{name}"] += int(value is not None)
                counter[f"null_{name}"] += int(value is None)
                if family == "hist_js":
                    counter[f"native_null_{name}"] += int(value is None)
        for one,two in (("p1_service_points_won","p2_return_points_won"),
                        ("p2_service_points_won","p1_return_points_won")):
            x,y=stats.get(one),stats.get(two)
            if x is not None and y is not None:
                if abs(float(x)+float(y)-1)>1e-6:
                    counter["inconsistent_serve_return_pairs"] += 1
            elif (x is None) != (y is None):
                counter["current_exact_complement_null_cells"] += 1
        pair_errors = 0
        pair_nulls = 0
        for own,opp in RECOVERY_PAIRS:
            own_v,opp_v=stats.get(own),stats.get(opp)
            if own_v is not None and not valid_rate(own_v) or opp_v is not None and not valid_rate(opp_v):
                pair_errors += 1
            elif own_v is not None and opp_v is not None and abs(own_v+opp_v-1)>1e-6:
                pair_errors += 1
            elif (own_v is None) != (opp_v is None):
                pair_nulls += 1
                counter["potential_pairwise_complement_cells"] += 1
                counter["candidate_"+(own if own_v is None else opp)] += 1
        if pair_errors:
            counter["matches_with_any_pair_error"] += 1
        if pair_nulls and pair_errors:
            counter["potential_complements_in_otherwise_conflicting_match"] += pair_nulls
            counter["matches_with_valid_candidate_and_other_pair_conflict"] += 1
        if not stats:
            counter[f"no_stats_{family}"] += 1
    return dict(sorted(counter.items())), dict(sorted(samples.items()))


def load_rows(history):
    import pyarrow.parquet as pq
    for path in sorted(history.glob("history-*.parquet")):
        pf = pq.ParquetFile(path)
        cols = ("match_id","stats_json","provider_context_json")
        if not set(cols).issubset(pf.schema_arrow.names):
            raise ValueError(f"Missing canonical columns in {path.name}")
        for batch in pf.iter_batches(batch_size=4096,columns=list(cols)):
            values = batch.to_pydict()
            for items in zip(*(values[col] for col in cols)):
                yield dict(zip(cols,items))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--history-dir",type=Path,required=True)
    ap.add_argument("--snapshot-report",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    snapshot=json.loads(args.snapshot_report.read_text())
    if snapshot.get("status")!="verified" or len(str(snapshot.get("manifest_sha256","")))!=64:
        raise ValueError("Current CDB coherent snapshot not independently pinned")
    counters,samples=profile(load_rows(args.history_dir))
    result={
        "schema":"BLINQ_CURRENT_CDB_SERVE_RETURN_COVERAGE_V1",
        "source":"verified_private_canonical_release_tbt-data-v1",
        "snapshot_manifest_sha256":snapshot["manifest_sha256"],
        "status":"read_only_current_cdb_verified",
        "counts":counters,"source_evidence_samples":samples,
        "candidate_from_uploaded_L2_validated":0,
        "approved_source_permissions_for_L2_established_here":False,
        "import_writes":0,
    }
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print("CDB_SERVE_RETURN_CURRENT_GAP_REPORT",json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
