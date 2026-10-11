"""Read-only WTA 2025 exact canonical-ID historical ranking NULL audit.

Never match using name fallback; source ranking snapshot must strictly predate
the match by 1..14 calendar days. No CDB or model writes.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import timezone
import gzip
import hashlib
import json
from pathlib import Path

YEAR = 2025
MAX_AGE_DAYS = 14

def audit_rows(matches, ranking, year_sha, source_hashes):
    if len(year_sha) != 64 or any(c not in "0123456789abcdef" for c in year_sha):
        raise ValueError("Canonical year SHA required")
    mapping = getattr(ranking, "_canonical_to_sackmann", None)
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("Verified ID crosswalk required")
    frequency = Counter(str(v) for v in mapping.values())
    counts, quarantined, months = Counter(), Counter(), {}
    stage, seen = [], set()
    for m in matches:
        day = m.scheduled_at.astimezone(timezone.utc).date()
        if day.year != YEAR or str(m.tour).lower() != "wta":
            continue
        mid = str(m.match_id)
        if not mid or mid in seen:
            raise ValueError("Duplicate or missing canonical match ID")
        seen.add(mid)
        counts["wta_matches"] += 1
        month = day.isoformat()[:7]
        months.setdefault(month, Counter())["matches"] += 1
        old = (m.player1_rank, m.player2_rank)
        if old[0] is not None and old[1] is not None:
            counts["rank_already_complete"] += 1
            continue
        counts["matches_with_rank_gaps"] += 1
        ids = (str(m.player1_id), str(m.player2_id))
        src = tuple(str(mapping.get(pid) or "") for pid in ids)
        if not all(src) or src[0] == src[1] or any(frequency[v] != 1 for v in src):
            quarantined["missing_or_nonunique_player_ids"] += 1
            continue
        counts["both_player_ids_attested"] += 1
        rows = (
            ranking._snapshot(m.player1_name, day, player_id=m.player1_id, max_age_days=MAX_AGE_DAYS),
            ranking._snapshot(m.player2_name, day, player_id=m.player2_id, max_age_days=MAX_AGE_DAYS),
        )
        if rows[0] is None or rows[1] is None:
            quarantined["prior_rank_snapshot_missing"] += 1
            continue
        if any(not 1 <= (day - item["date"]).days <= MAX_AGE_DAYS for item in rows):
            quarantined["future_same_day_or_stale_rank"] += 1
            continue
        counts["both_source_snapshots_valid"] += 1
        if any(old[i] is not None and int(old[i]) != int(rows[i]["rank"]) for i in (0, 1)):
            quarantined["existing_rank_disagreement"] += 1
            continue
        additions = {f"player{i+1}_rank":int(rows[i]["rank"]) for i in (0, 1) if old[i] is None}
        if not additions or any(not 1 <= v <= 10000 for v in additions.values()):
            quarantined["invalid_rank_domain"] += 1
            continue
        stage.append({
            "schema":1, "status":"CANDIDATE_NOT_WRITER_APPROVED",
            "canonical_match_id":mid, "canonical_year":YEAR, "canonical_year_sha256":year_sha,
            "scheduled_at":m.scheduled_at.astimezone(timezone.utc).isoformat(),
            "player1_id":ids[0], "player2_id":ids[1],
            "source_player1_id":src[0], "source_player2_id":src[1],
            "source_week_p1":rows[0]["date"].isoformat(), "source_week_p2":rows[1]["date"].isoformat(),
            "expected_player1_rank":old[0], "expected_player2_rank":old[1],
            "add_only_null_fields":additions,
            "temporal_policy":"source_before_match_1_to_14_days",
        })
        counts["candidate_matches"] += 1
        counts["candidate_rank_cells"] += len(additions)
        months[month]["candidate_matches"] += 1
        months[month]["candidate_cells"] += len(additions)
    return {
        "schema":1, "status":"READ_ONLY_WTA2025_ID_RANK_CDB_GAPS",
        "year":YEAR, "canonical_year_sha256":year_sha, "source_sha256":source_hashes,
        "counts":dict(counts), "quarantined":dict(quarantined),
        "months":{key:dict(value) for key,value in sorted(months.items())},
        "write_authorized":False, "canonical_mutated":False, "model_trained":False,
        "model_promoted":False, "provider_api_requests":0,
        "next_gate":"Independent source-rights confirmation, fresh year SHA, per-match CAS, single-writer lock, immutable backup, complete remote readback before any rank write",
    }, stage

def main():
    from _bootstrap import ROOT  # noqa: F401
    from release_store import ReleaseStore
    from rank_feature_inputs import load_rank_feature_inputs
    from tbt.data.history_snapshot import load_manifest, load_partitions
    from tbt.data.history_safety import sanitize_history_identities
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo",default="BackstageTalks/tbt-data")
    ap.add_argument("--out",required=True,type=Path)
    a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    history=a.out/"history"
    ReleaseStore(a.repo,"tbt-data-v1",history).download(require_bundle_manifest=True)
    matches,safety=sanitize_history_identities(load_partitions(history))
    if safety.get("quarantined_rows") or len(matches)<994101:
        raise ValueError("Canonical history unsafe/incomplete")
    rank=load_rank_feature_inputs(a.repo,a.out/"rank-inputs",matches)
    manifest=load_manifest(history)["years"][str(YEAR)]
    sha=hashlib.sha256((history/f"history-{YEAR}.parquet").read_bytes()).hexdigest()
    if sha!=manifest.get("sha256"):
        raise ValueError("Year SHA/manifest mismatch")
    source_hashes={key:value["sha256"] for key,value in rank.report["sources"].items()}
    report,stage=audit_rows(matches,rank.wta,sha,source_hashes)
    report["canonical_rows"]=len(matches)
    report["wta_crosswalk"]=rank.report["wta_crosswalk"]
    stage_path=a.out/"wta2025-rank-null-candidates.jsonl.gz"
    with stage_path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw,mode="wb",filename="",mtime=0) as output:
            for row in stage:
                output.write((json.dumps(row,sort_keys=True,ensure_ascii=False)+"\n").encode())
    report["stage_sha256"]=hashlib.sha256(stage_path.read_bytes()).hexdigest()
    (a.out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("WTA_ID_RANK_CDB_DELTA",json.dumps({"counts":report["counts"],"quarantined":report["quarantined"],"canonical_year_sha256":sha},sort_keys=True))
if __name__=="__main__":
    main()
