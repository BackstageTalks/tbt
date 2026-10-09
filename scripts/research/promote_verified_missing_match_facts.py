#!/usr/bin/env python3
"""Private-only, no-provider-call, fail-closed historical FACT enrichment.

Only missing stats on ALREADY IDENTIFIED canonical matches can be written.
Futures matches not proven in canonical are quarantined, never appended.
PBP/PBPX are matched by exact identities and dates via existing guarded linkers.
All release writes target private tbt-data; only audit numbers are logged.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from release_store import ReleaseStore
from research.nightly_private_canonical_gap_scan import (
    REPO, SOURCE, WORK, reconstruct_sources, verify_backup, raw, save_private,
    release_history,
)

ORIGINAL = WORK / "original"
SHADOW = WORK / "enrichment-shadow"
OUT = WORK / "fact-promotion"

def run(*args):
    print("Running guarded step:", args[0], Path(str(args[1])).name if len(args)>1 else "", flush=True)
    subprocess.run(list(map(str,args)),check=True)

def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""):
            h.update(b)
    return h.hexdigest()

_PINNED_BACKUP_PROOF = None
def assert_remote_unchanged():
    # Download and verify the sealed backup only once: repeated gh release
    # download without --clobber fails on a pre-existing proof.json.
    global _PINNED_BACKUP_PROOF
    if _PINNED_BACKUP_PROOF is None:
        _PINNED_BACKUP_PROOF = verify_backup()
    expected={name:(meta["source_id"], meta["bytes"],"sha256:"+meta["sha256"])
              for name,meta in _PINNED_BACKUP_PROOF["sha256"].items()}
    if release_history()!=expected:
        raise RuntimeError("Canonical release changed since verified backup; abort safely")
    return _PINNED_BACKUP_PROOF

def list_rows(directory):
    manifest=json.loads((directory/"history_manifest.json").read_text())
    years=manifest["years"]
    return sum(int(m["rows"]) for m in years.values()),set(int(y) for y in years)

def check_stat_only(before,after,years):
    output={"changed_years": sorted(years),"new_stat_fields":0,"enriched_match_rows":0,
            "changed_stats_by_year":{},"same_match_ids":True,
            "immutable_match_fields_equal":True,"existing_stats_unchanged":True}
    allowed="stats_json"
    for year in sorted(years):
        name=f"history-{year:04d}.parquet"
        a=pd.read_parquet(before/name).sort_values("match_id").reset_index(drop=True)
        b=pd.read_parquet(after/name).sort_values("match_id").reset_index(drop=True)
        if list(a.columns)!=list(b.columns) or len(a)!=len(b):
            raise RuntimeError("Columns or match count changed: "+name)
        for col in a.columns:
            if col==allowed: continue
            if not a[col].equals(b[col]):
                raise RuntimeError("Immutable match field altered: "+name+" "+col)
        added=0
        updated=0
        for old_text,new_text in zip(a[allowed],b[allowed]):
            old=json.loads(old_text or "{}")
            new=json.loads(new_text or "{}")
            if not isinstance(old,dict) or not isinstance(new,dict):
                raise RuntimeError("Invalid historical statistic JSON")
            for field,value in old.items():
                if field not in new:
                    raise RuntimeError("Missing existing statistic: "+field)
                other=new[field]
                if value is None and other is not None:
                    added+=1
                elif value is not None and other!=value:
                    raise RuntimeError("Old statistic overwritten: "+field)
            added+=sum(1 for k,v in new.items() if k not in old and v is not None)
            if old != new:
                updated+=1
        output["changed_stats_by_year"][str(year)]={"fields_added":added,"matches_enriched":updated}
        output["new_stat_fields"]+=added
        output["enriched_match_rows"]+=updated
        if added==0 and digest(before/name)!=digest(after/name):
            raise RuntimeError("History file bytes changed without improved coverage: "+name)
    return output

def main():
    if not os.environ.get("GH_TOKEN"):
        raise SystemExit("Missing access to private destination")
    proof=assert_remote_unchanged()
    outputs={"schema":1,"run_id":os.environ.get("GITHUB_RUN_ID"),
       "started_utc":datetime.now(timezone.utc).isoformat(),
       "backup_tag":"blinq-canonical-backup-37864914634",
       "status":"running","production_mutated":False,"model_promoted":False,"provider_requests":0}
    OUT.mkdir(parents=True,exist_ok=True)
    target=f"audit/autonomous-canonical-safe-enrichment-{os.environ['GITHUB_RUN_ID']}.json"
    published=False
    changed=[]
    try:
        outputs["source_manifest"]=reconstruct_sources()
        for name,path in [
          ("ATP_Singles_pbpx.csv","research/offline-sources/drive-pbpx-20261009/ATP_Singles_pbpx.csv"),
          ("WTA_Singles_pbpx.csv","research/offline-sources/drive-pbpx-20261009/WTA_Singles_pbpx.csv"),
          ("pbp_matches_atp_main_archive_20261004.csv","research/pointbypoint/pbp_matches_atp_main_archive_20261004.csv"),
        ]:
            payload=raw(path)
            if not payload or not payload.startswith(b""):
                raise RuntimeError("Missing PBP source "+name)
            (SOURCE/name).write_bytes(payload)
        outputs["additional_pbp_sources"]=["ATP_Singles_pbpx.csv","WTA_Singles_pbpx.csv","pbp_matches_atp_main_archive_20261004.csv"]
        store=ReleaseStore(REPO,"tbt-data-v1",ORIGINAL)
        store.download(require_bundle_manifest=True)
        assert_remote_unchanged()
        original_rows, original_years=list_rows(ORIGINAL)
        outputs["canonical_before_rows"]=original_rows
        SHADOW.mkdir(parents=True,exist_ok=True)
        for file in ORIGINAL.iterdir():
            if file.is_file():
                shutil.copy2(file,SHADOW/file.name)
        # Guarded enrichment: 0 new matches. Conflicts quarantined by existing importer.
        run(sys.executable,"scripts/import_blinq_offline_bundle.py",
             "--history-dir",SHADOW,
             "--futures-csv",SOURCE/"blinq_atp_futures_quali_2018_2026.csv",
             "--charting-csv",SOURCE/"blinq_charting_atp_core_features.csv",
             "--charting-csv",SOURCE/"blinq_charting_wta_core_features.csv",
             "--out-dir",OUT/"futures_charting",
             "--existing-only","--write-partitions")
        factual=json.loads((OUT/"futures_charting"/"report.json").read_text())
        outputs["futures_charting"]=factual
        if factual["counts"].get("foundation_new_matches",0):
            raise RuntimeError("Existing-only importer added new matches")
        # Derive actual service/return ratios from match tapes using exact-day/pair matching.
        run(sys.executable,"scripts/link_pointbypoint_serve_return.py",
             "--history-dir",SHADOW,"--source-dir",SOURCE,"--out-dir",OUT/"pbp_link")
        linked=json.loads((OUT/"pbp_link"/"report.json").read_text())
        outputs["pbp_link_report"]=linked
        run(sys.executable,"scripts/import_offline_linked_serve_return.py",
             "--stage",OUT/"pbp_link"/"auto_linked.jsonl",
             "--history-dir",SHADOW,"--out-dir",OUT/"pbp_import",
             "--write-partitions","--write-history-dir",SHADOW)
        linked_import=json.loads((OUT/"pbp_import"/"report.json").read_text())
        outputs["pbp_import_report"]=linked_import
        changed=sorted(set(factual["changed_years"])|set(linked_import["changed_years"]))
        after_rows, after_years=list_rows(SHADOW)
        if original_rows!=after_rows or original_years!=after_years:
            raise RuntimeError("Canonical row count or partition inventory changed")
        outputs["fact_only_gate"]=check_stat_only(ORIGINAL,SHADOW,changed)
        outputs["canonical_projected_rows"]=after_rows
        if outputs["fact_only_gate"]["new_stat_fields"]==0:
            outputs["status"]="no_missing_verified_facts"
            return
        # Verify the complete shadow set can be reopened under canonical validation.
        from tbt.data.history_snapshot import load_partitions
        from tbt.data.history_safety import sanitize_history_identities
        shadow_matches, safety=sanitize_history_identities(load_partitions(SHADOW))
        if len(shadow_matches)!=after_rows or safety.get("quarantined_rows"):
            raise RuntimeError("Full shadow identity validation failed")
        del shadow_matches
        outputs["identity_safety"]=safety
        assert_remote_unchanged()
        # Pre-upload peer audit is persisted to PRIVATE repo (no sensitive match rows).
        outputs["status"]="ready_to_promote"
        save_private(target,outputs)
        # Publish only proven field additions. Bundle manifest goes LAST; readers
        # fail closed during partial upload. Pre-existing backup remains untouched.
        paths=[SHADOW/f"history-{y:04d}.parquet" for y in changed]
        paths.append(SHADOW/"history_manifest.json")
        store.upload_bundle(paths,before_upload=assert_remote_unchanged)
        published=True
        fresh=ReleaseStore(REPO,"tbt-data-v1",WORK/"remote_verified")
        fresh.download(require_bundle_manifest=True)
        final_rows,_=list_rows(WORK/"remote_verified")
        if final_rows!=after_rows:
            raise RuntimeError("Persisted canonical row count changed after publish")
        for path in paths:
            readback=WORK/"remote_verified"/path.name
            if digest(path)!=digest(readback):
                raise RuntimeError("Canonical persisted readback checksum mismatch "+path.name)
        outputs["canonical_readback_rows"]=final_rows
        outputs["production_mutated"]=True
        outputs["status"]="verified_canonical_fact_enrichment"
        outputs["persisted_readback"]="PASS"
    except Exception as exc:
        outputs["status"]="failed_or_quarantined"
        outputs["failure"]=str(exc)[:1100]
        if published:
            outputs["rollback_attempted"]=True
            try:
                prior=ReleaseStore(REPO,"tbt-data-v1",WORK/"rollback")
                for y in changed:
                    (WORK/"rollback").mkdir(parents=True,exist_ok=True)
                    shutil.copy2(ORIGINAL/f"history-{y:04d}.parquet",WORK/"rollback"/f"history-{y:04d}.parquet")
                shutil.copy2(ORIGINAL/"history_manifest.json",WORK/"rollback"/"history_manifest.json")
                paths=[WORK/"rollback"/f"history-{y:04d}.parquet" for y in changed]
                paths.append(WORK/"rollback"/"history_manifest.json")
                prior.upload_bundle(paths)
                outputs["rollback_status"]="attempted_original_partition_restore"
            except Exception as rollback_exc:
                outputs["rollback_failure"]=str(rollback_exc)[:300]
        raise
    finally:
        outputs["ended_utc"]=datetime.now(timezone.utc).isoformat()
        save_private(target,outputs)
        print(json.dumps({"status":outputs["status"],"canonical_mutated":outputs["production_mutated"],
            "added_fields":outputs.get("fact_only_gate",{}).get("new_stat_fields"),
            "readback":outputs.get("persisted_readback","none"),"report":target},ensure_ascii=False))
if __name__=="__main__":
    main()
