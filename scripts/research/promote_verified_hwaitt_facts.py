#!/usr/bin/env python3
"""Hwaitt factual serve/return enrichment, guarded by a sealed private snapshot.

Only import missing values into matches with exact proven canonical identity.
Never create matches, change existing values, expose raw data publicly, or promote
a model. Entire publication is gated by a same-run private backup and readback.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from release_store import ReleaseStore
from research import nightly_private_canonical_gap_scan as gap
from research.promote_verified_missing_match_facts import (
    assert_remote_unchanged, check_stat_only, digest, list_rows
)
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities

REPO = "BackstageTalks/tbt-data"
WORK = Path(".cache/tbt/hwaitt-governed")
RAW = WORK / "raw"
ORIGINAL = WORK / "before"
SHADOW = WORK / "shadow"
OUT = WORK / "checks"
PROVENANCE = {
    "source": "Kaggle hwaitt/tennis-20112019",
    "license": "CC BY-NC 4.0",
    "atp.csv": {"sha256":"c2d0b8545443dee0e143f293a3c80f54bd9b3c87e5eae0b49739f51c1d62b507",
                "rows":216981},
    "wta.csv": {"sha256":"1467b2efd02288502f518662fe3ad3e1c9121e7e59a0e65f690f6ec779591548",
                "rows":134810},
}
TARGET = f"audit/hwaitt-current-canonical-import-{os.environ['GITHUB_RUN_ID']}.json"

def cmd(command, *, label):
    r = subprocess.run(list(map(str,command)),capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(label+" returned nonzero exit status "+str(r.returncode))
    return r.stdout[-1600:]

def verify_source():
    RAW.mkdir(parents=True)
    package = RAW/"source.zip"
    cmd(["curl","--fail","--location","--retry","4","--retry-delay","3",
         "--connect-timeout","30","--max-time","900",
         "https://www.kaggle.com/api/v1/datasets/download/hwaitt/tennis-20112019",
         "--output",package],label="Kaggle source download")
    with zipfile.ZipFile(package) as archive:
        members={}
        for m in archive.infolist():
            if m.is_dir():continue
            if m.filename.split("/")[-1] in ("atp.csv","wta.csv"):
                basename=m.filename.split("/")[-1]
                if basename in members: raise RuntimeError("Ambiguous source member")
                members[basename]=m
        if set(members)!={"atp.csv","wta.csv"}:raise RuntimeError("Unrecognized source archive")
        for name, member in members.items():
            target=RAW/name
            with archive.open(member) as inp, target.open("wb") as out:
                shutil.copyfileobj(inp,out)
    package.unlink()
    verified={}
    for name in ("atp.csv","wta.csv"):
        f=RAW/name
        h=digest(f)
        if h!=PROVENANCE[name]["sha256"]:
            raise RuntimeError("Hwaitt source content hash changed: "+name)
        with f.open("r",encoding="utf-8-sig",newline="") as reader:
            count=max(0,sum(1 for row in csv.reader(reader))-1)
        if count!=PROVENANCE[name]["rows"]:
            raise RuntimeError("Source row count mismatch: "+name)
        verified[name]={"sha256":h,"rows":count,"bytes":f.stat().st_size}
    return verified

def main():
    if not os.environ.get("GH_TOKEN"):
        raise SystemExit("Missing private release credential")
    OUT.mkdir(parents=True,exist_ok=False)
    audit={
        "schema":1,"status":"running","run_id":os.environ["GITHUB_RUN_ID"],
        "started_at":datetime.now(timezone.utc).isoformat(),
        "source_license":"CC BY-NC 4.0","private_repository":REPO,
        "canonical_mutated":False,"model_promoted":False,"api_requests":0,
    }
    attempted_publish=False
    changed_years=[]
    store=None
    try:
        # Always seal and read back the ACTUAL current canonical release.
        cmd([sys.executable,"scripts/research/private_canonical_snapshot_v2.py"],
            label="Private canonical backup")
        gap.BACKUP_TAG="blinq-canonical-backup-"+os.environ["GITHUB_RUN_ID"]
        audit["backup_tag"]=gap.BACKUP_TAG
        proof=assert_remote_unchanged()
        audit["backup_rows"]=proof["row_count"]
        audit["source_verified"]=verify_source()
        store=ReleaseStore(REPO,"tbt-data-v1",ORIGINAL)
        store.download(require_bundle_manifest=True)
        assert_remote_unchanged()
        n0, years0=list_rows(ORIGINAL)
        if n0!=proof["row_count"]:
            raise RuntimeError("Row count diverges from sealed backup")
        audit["canonical_before_rows"]=n0
        SHADOW.mkdir()
        for file in ORIGINAL.iterdir():
            if file.is_file():shutil.copy2(file,SHADOW/file.name)

        cmd([sys.executable,"scripts/link_offline_serve_return.py",
             "--history-dir",SHADOW,
             "--kaggle-hwaitt-csv",RAW/"atp.csv",
             "--kaggle-hwaitt-csv",RAW/"wta.csv",
             "--out-dir",OUT/"link"],label="Hwaitt current-release strict linker")
        link=json.loads((OUT/"link"/"report.json").read_text())
        audit["link_summary"]={
            "canonical_rows":link.get("canonical_rows"),
            "source_rows":link.get("source_rows"),
            "counts":link.get("counts"),
            "staged_field_counts":link.get("staged_field_counts"),
            "quality_ready_before":link.get("quality_ready_before"),
            "quality_ready_projected_added":link.get("quality_ready_projected_added"),
        }
        if link.get("canonical_rows")!=n0:raise RuntimeError("Linker canonical mismatch")
        stage=OUT/"link"/"auto_linked.jsonl"
        cmd([sys.executable,"scripts/import_offline_linked_serve_return.py",
             "--stage",stage,"--history-dir",SHADOW,
             "--out-dir",OUT/"dry"],label="Strict no-write Hwaitt dry-run")
        dry=json.loads((OUT/"dry"/"report.json").read_text())
        audit["dry_run"]=dry
        if dry["stage_rows"]!=link.get("counts",{}).get("staged_matches",0):
            raise RuntimeError("Staged match count and linker mismatch")
        for key in ("identity_missing","identity_changed","invalid_stats","stat_conflicts"):
            if dry.get("counts",{}).get(key,0):
                raise RuntimeError("Importer conflict gate failed: "+key)
        if not dry.get("changed_years"):
            audit["status"]="no_verified_missing_fields"
            return
        cmd([sys.executable,"scripts/import_offline_linked_serve_return.py",
             "--stage",stage,"--history-dir",SHADOW,
             "--out-dir",OUT/"write",
             "--write-partitions","--write-history-dir",SHADOW],
             label="Write verified missing fields to SHADOW only")
        write=json.loads((OUT/"write"/"report.json").read_text())
        audit["local_shadow"]=write
        changed_years=write["changed_years"]
        if changed_years!=dry["changed_years"] or write["counts"]!=dry["counts"]:
            raise RuntimeError("Shadow/dry-run report differs")
        n1, years1=list_rows(SHADOW)
        if n0!=n1 or years0!=years1:raise RuntimeError("Canonical match count changed")
        gate=check_stat_only(ORIGINAL,SHADOW,changed_years)
        audit["fact_only_gate"]=gate
        if gate["new_stat_fields"]<=0:
            raise RuntimeError("No new safe fact values after positive dry-run")
        matches,safety=sanitize_history_identities(load_partitions(SHADOW))
        if len(matches)!=n0 or safety.get("quarantined_rows"):
            raise RuntimeError("Full SHADOW identity integrity failed")
        del matches
        audit["identity_safety"]={"quarantined_rows":0,"matches":n0}
        assert_remote_unchanged()
        audit["status"]="guarded_pre_promotion_verified"
        gap.save_private(TARGET,audit)
        # Publication changes ONLY year partitions with verified NULL->VALUE stats.
        paths=[SHADOW/f"history-{year:04d}.parquet" for year in changed_years]
        paths.append(SHADOW/"history_manifest.json")
        attempted_publish=True
        store.upload_bundle(paths,before_upload=assert_remote_unchanged)
        remote=ReleaseStore(REPO,"tbt-data-v1",WORK/"readback")
        remote.download(require_bundle_manifest=True)
        n2, years2=list_rows(WORK/"readback")
        if n2!=n0 or years2!=years0:raise RuntimeError("Persisted row/years mismatch")
        for p in paths:
            if digest(p)!=digest(WORK/"readback"/p.name):
                raise RuntimeError("Persisted digest mismatch for "+p.name)
        matches,safety=sanitize_history_identities(load_partitions(WORK/"readback"))
        if len(matches)!=n0 or safety.get("quarantined_rows"):
            raise RuntimeError("Persisted identity verification failed")
        audit["canonical_mutated"]=True
        audit["persisted_readback"]="PASS"
        audit["canonical_after_rows"]=n2
        audit["quality_ready_added"]=write.get("quality_ready_added")
        audit["status"]="verified_canonical_hwaitt_enrichment"
    except Exception as e:
        audit["status"]="blocked_or_failed"
        audit["failure_type"]=type(e).__name__
        audit["failure_summary"]=str(e)[:500]
        if attempted_publish:
            audit["requires_manual_rollback_review"]=True
            # Do not automatically overwrite a possibly concurrently updated release.
        raise
    finally:
        audit["finished_at"]=datetime.now(timezone.utc).isoformat()
        gap.save_private(TARGET,audit)
        print(json.dumps({"status":audit["status"],"new_facts":audit.get("fact_only_gate",{}).get("new_stat_fields",0),
                          "persisted_readback":audit.get("persisted_readback"),
                          "production_changed":audit["canonical_mutated"],"audit":TARGET},ensure_ascii=False))
if __name__=="__main__":
    main()
