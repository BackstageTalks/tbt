"""WTA 2026 PIT weekly rank stage -> exact null-only current CDB year.

The old stage was pinned before an ATP-only year rewrite. Rebase proves *all*
WTA rows identical in the current year and old independently backed-up year.
This local script performs no network calls, releases, API calls, or training.
Publication lock, immutable prewrite backup and independent remote readback
belong to the guarded workflow.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import pandas as pd
from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_manifest, update_year_manifest

YEAR = 2026
STAGE_SHA = "d8353bb92c8fbca596cf8d423ef926bbeb2d6ae51d3e4ddd686d23837d3976f4"
REPORT_SHA = "d70c7dce0ce8fc413a226ebff68ab2ae4628e2f8799ec26af6e2980a8f8cf086"
ORIGINAL_SHA = "b945528573a8488a5c03eec66b0987791939313cc1099b12d44a9d4a95893bc6"
EXPECTED_MATCHES = 9844
EXPECTED_VALUES = 19688
ALLOWED = {"player1_rank", "player2_rank"}
PROVENANCE = "_tbt_rank_provenance"


def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def missing(v):
    return v is None or bool(pd.isna(v))


def check_frame(directory, *, expected_sha=None):
    directory=Path(directory)
    f=directory/f"history-{YEAR}.parquet"
    meta=(load_manifest(directory).get("years") or {}).get(str(YEAR),{})
    hash_=digest(f)
    if (meta.get("sha256")!=hash_ or meta.get("asset")!=f.name
            or (expected_sha is not None and hash_!=expected_sha)):
        raise ValueError("2026 canonical year SHA or manifest does not match")
    df=pd.read_parquet(f)
    if int(meta.get("rows",-1))!=len(df):
        raise ValueError("Row count disagreement")
    required={"match_id","tour","scheduled_at","player1_id","player2_id",
              "player1_rank","player2_rank","provider_context_json"}
    if not required.issubset(df.columns):
        raise ValueError("Canonical columns missing")
    if df["match_id"].astype(str).duplicated().any():
        raise ValueError("Duplicate current canonical match identities")
    return df,hash_


def load_candidates(stage_file, report_file):
    if digest(stage_file)!=STAGE_SHA or digest(report_file)!=REPORT_SHA:
        raise ValueError("Original WTA stage/report SHA mismatch")
    report=json.loads(Path(report_file).read_text())
    if (report.get("schema")!=1
            or report.get("status")!="READ_ONLY_WTA2026_ID_RANK_CDB_GAPS"
            or report.get("canonical_year_sha256")!=ORIGINAL_SHA
            or report.get("stage_sha256")!=STAGE_SHA
            or report.get("canonical_mutated") is not False
            or report.get("model_trained") is not False
            or report.get("model_promoted") is not False
            or report.get("provider_api_requests")!=0
            or report.get("counts",{}).get("candidate_matches")!=EXPECTED_MATCHES
            or report.get("counts",{}).get("candidate_rank_cells")!=EXPECTED_VALUES):
        raise ValueError("WTA stage audit status/cardinality invalid")
    with gzip.open(stage_file,"rt",encoding="utf-8") as f:
        rows=[json.loads(l) for l in f if l.strip()]
    if len(rows)!=EXPECTED_MATCHES:
        raise ValueError("WTA source stage cardinality mismatch")
    seen=set()
    idmap,reverse={},{}
    for item in rows:
        mid=str(item.get("canonical_match_id") or "")
        if (mid in seen or not mid or item.get("schema")!=1
                or item.get("status")!="CANDIDATE_NOT_WRITER_APPROVED"
                or item.get("canonical_year")!=YEAR
                or item.get("canonical_year_sha256")!=ORIGINAL_SHA
                or item.get("temporal_policy")!="source_before_match_1_to_14_days"):
            raise ValueError("Invalid stage match ID, generation or time policy")
        seen.add(mid)
        vals=item.get("add_only_null_fields")
        if not isinstance(vals,dict) or set(vals)!=ALLOWED:
            raise ValueError("Both side ranks must be explicitly null-to-value")
        for key,v in vals.items():
            if isinstance(v,bool) or not isinstance(v,int) or not 1<=v<=10000:
                raise ValueError("Invalid incoming rank")
            if item.get("expected_"+key) is not None:
                raise ValueError("Stage's original-cell precondition is not null")
        day=pd.Timestamp(item.get("scheduled_at"))
        if day.tzinfo is None or day.tz_convert("UTC").year!=YEAR:
            raise ValueError("Stage timestamp must be UTC-aware and in 2026")
        for i in (1,2):
            pid=str(item.get(f"player{i}_id") or "")
            sid=str(item.get(f"source_player{i}_id") or "")
            if not pid or not sid or (pid in idmap and idmap[pid]!=sid):
                raise ValueError("Non-unique canonical to WTA source player ID")
            if sid in reverse and reverse[sid]!=pid:
                raise ValueError("Non-unique WTA source to canonical player ID")
            idmap[pid]=sid
            reverse[sid]=pid
            w=date.fromisoformat(item[f"source_week_p{i}"])
            age=(day.date()-w).days
            if not 1<=age<=14:
                raise ValueError("Source rank was stale, same-day or in future")
    return rows, report


def ensure_wta_rebase_identical(old,current):
    """ATP ranks may change; not even one unrelated WTA cell may drift."""
    m1=old["tour"].astype(str).str.lower()=="wta"
    m2=current["tour"].astype(str).str.lower()=="wta"
    a=old.loc[m1].sort_values("match_id").reset_index(drop=True)
    b=current.loc[m2].sort_values("match_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(a,b,check_dtype=True,check_exact=True)
    return len(a)


def patch(current, rows, *, expected_matches=EXPECTED_MATCHES, expected_values=EXPECTED_VALUES):
    out=current.copy(deep=True)
    ix=dict(zip(current["match_id"].astype(str),current.index))
    counts=Counter()
    for item in rows:
        mid=item["canonical_match_id"]
        if mid not in ix:
            raise ValueError("Original WTA match missing from current CDB")
        idx=ix[mid]
        orig=current.loc[idx]
        if (str(orig["tour"]).lower()!="wta"
                or pd.Timestamp(orig["scheduled_at"]).isoformat()!=item["scheduled_at"]
                or str(orig["player1_id"])!=str(item["player1_id"])
                or str(orig["player2_id"])!=str(item["player2_id"])):
            raise ValueError("Match source-to-CDB identity drift")
        for key in ALLOWED:
            if not missing(orig[key]):
                raise ValueError("Null-only rank precondition changed")
        raw=orig["provider_context_json"]
        context=json.loads(raw) if not missing(raw) else {}
        if not isinstance(context,dict):
            raise ValueError("Invalid history provider context")
        provenance={
            "source":"wta_sackmann_weekly_verified_canonical_id",
            "source_week_p1":item["source_week_p1"],
            "source_week_p2":item["source_week_p2"],
            "source_player1_id":str(item["source_player1_id"]),
            "source_player2_id":str(item["source_player2_id"]),
            "point_in_time":True
        }
        if PROVENANCE in context and context[PROVENANCE]!=provenance:
            raise ValueError("Existing rank provenance conflict")
        context[PROVENANCE]=provenance
        out.at[idx,"provider_context_json"]=json.dumps(context,sort_keys=True,
                                               separators=(",",":"),ensure_ascii=False)
        for key in ("player1_rank","player2_rank"):
            out.at[idx,key]=item["add_only_null_fields"][key]
            counts[key+"_filled"]+=1
        counts["changed_matches"]+=1
    if (counts["changed_matches"]!=expected_matches
            or counts["player1_rank_filled"]+counts["player2_rank_filled"]!=expected_values):
        raise ValueError("Unexpected WTA additive rank stage output")
    other=[k for k in current.columns if k not in ALLOWED|{"provider_context_json"}]
    pd.testing.assert_frame_equal(out[other],current[other],check_dtype=True)
    untouched=~current["match_id"].astype(str).isin({r["canonical_match_id"] for r in rows})
    pd.testing.assert_frame_equal(out.loc[untouched],current.loc[untouched],check_dtype=True)
    return out,dict(counts)


def run(mode, old_dir, before_dir, after_dir, stage_file, report_file):
    if mode not in ("dry-run","write","verify"):
        raise ValueError("Unknown WTA import mode")
    old,_=check_frame(old_dir,expected_sha=ORIGINAL_SHA)
    current,current_sha=check_frame(before_dir)
    n=ensure_wta_rebase_identical(old,current)
    stage,report=load_candidates(stage_file,report_file)
    expected,counts=patch(current,stage)
    if mode=="write":
        if Path(before_dir).resolve()==Path(after_dir).resolve():
            raise ValueError("In-place write forbidden")
        target_dir=Path(after_dir)
        target_dir.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(Path(before_dir)/"history_manifest.json",
                        target_dir/"history_manifest.json")
        target=target_dir/f"history-{YEAR}.parquet"
        temp=target.with_suffix(".parquet.tmp")
        try:
            expected.to_parquet(temp,compression="zstd",engine="pyarrow",index=False)
            pd.testing.assert_frame_equal(pd.read_parquet(temp),expected,check_exact=True)
            temp.replace(target)
            update_year_manifest(target_dir,YEAR,{
                "sha256":digest(target),"bytes":target.stat().st_size,
                "rows":len(expected)
            },extra={"coverage_status":"WTA2026_verified_id_weekly_PIT_rank_addition"})
        finally:
            if temp.exists():
                temp.unlink()
    elif mode=="verify":
        persisted,_=check_frame(after_dir)
        pd.testing.assert_frame_equal(persisted,expected,check_dtype=True,
                                      check_exact=True)
    return {
        "schema":1,"mode":mode,
        "status":"verified_exact_full_year" if mode=="verify" else "validated_"+mode,
        "source_stage_sha256":digest(stage_file),"original_year_sha256":ORIGINAL_SHA,
        "current_before_sha256":current_sha,
        "after_sha256":digest(Path(after_dir)/f"history-{YEAR}.parquet")
                     if mode!="dry-run" else None,
        "canonical_rows_rechecked":len(current),"wta_rows_unchanged_in_rebase":n,
        "counts":counts,"overwrite_existing_rank_values":0,
        "model_trained":False,"model_promoted":False,"provider_api_requests":0,
        "production_mutated_by_script":False
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=("dry-run","write","verify"),required=True)
    for k in ("old_dir","before_dir","after_dir","stage_file","report_file","out"):
        p.add_argument("--"+k.replace("_","-"),required=True,type=Path)
    a=p.parse_args()
    res=run(a.mode,a.old_dir,a.before_dir,a.after_dir,a.stage_file,a.report_file)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(res,indent=2,sort_keys=True)+"\n")
    print(json.dumps(res,sort_keys=True))


if __name__=="__main__":
    main()
