#!/usr/bin/env python3
"""Reclassify exact prior PRIVATE Drive audit rejections, not user source rows.

Consumes a pinned pre-existing read-only archive, checks every embedded SHA,
retains all source file IDs/reasons, and ranks safe *review work*. Never
downloads Drive or sports APIs and cannot authorize CDB writes.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

SHA=re.compile(r"^[0-9a-f]{64}$")
PINNED_BUNDLE_SHA="a5d43ac0a55cc0d0fa7bf79c8dac0135054d905434e2a642944f2353a3b71af4"
STATES={"QUARANTINE","NEEDS_FORMAT_ADAPTER","DEFERRED_BUDGET",
        "NEEDS_LARGE_FILE_SHARD"}
MATCH_WORDS=re.compile(r"match|score|result|stat|service|serve|return|challeng|futures|wta|atp|itf|pbp|point",re.I)
RECENT_WORDS=re.compile(r"202[2-6]",re.I)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def read_verified_bundle(path, expected):
    if not SHA.fullmatch(expected): raise ValueError("Missing pinned archive SHA-256")
    blob=Path(path).read_bytes()
    if digest(blob)!=expected: raise ValueError("Pinned Drive audit private archive checksum differs")
    docs={}
    with tarfile.open(fileobj=io.BytesIO(blob),mode="r:gz") as archive:
        members=archive.getmembers()
        if len(members)>30 or sum(x.size for x in members)>95*1024*1024:
            raise ValueError("Unsafe private audit archive expansion")
        for member in members:
            if member.isdir() and member.name in (".","./"):continue
            name=member.name.removeprefix("./")
            if not member.isfile() or name!=Path(name).name or name in docs or member.size>35*1024*1024:
                raise ValueError("Unsafe or duplicate original audit archive member")
            f=archive.extractfile(member)
            if f is None:raise ValueError("Missing archive member")
            docs[name]=f.read()
    if not {"files.json","report.json","SHA256SUMS"}.issubset(docs):
        raise ValueError("Original audit missing required file-status proof")
    statements={}
    for line in docs["SHA256SUMS"].decode().splitlines():
        parts=line.split(None,1)
        if len(parts)!=2:raise ValueError("Bad inner SHA256 manifest")
        name=parts[1].lstrip("*")
        if not SHA.fullmatch(parts[0]) or name not in docs or name in statements:
            raise ValueError("Unknown/duplicate inner SHA entry")
        statements[name]=parts[0]
    for name,sha in statements.items():
        if digest(docs[name])!=sha:
            raise ValueError("Original audit embedded file changed: "+name)
    if set(docs)-{"SHA256SUMS"} != set(statements):
        raise ValueError("Incomplete private source audit checksum manifest")
    return docs

def suffix(name):
    s=str(name or "").lower()
    for ext in (".jsonl.gz",".json.gz",".csv.gz",".xlsx",".jsonl",".csv",".tsv",
                ".zip",".xls",".txt",".json",".sqlite",".parquet",".gz"):
        if s.endswith(ext):return ext
    return Path(s).suffix or "(unknown)"

def reason_kind(reason):
    s=str(reason or "").lower()
    if any(x in s for x in ("permission","forbidden","403","401","not found","404")):
        return "ACCESS_OR_ORIGIN_CHANGED"
    if any(x in s for x in ("429","timeout","timed out","connection","503","502","retry","network","download")):
        return "RETRY_READ_ONLY_DOWNLOAD"
    if any(x in s for x in ("utf","decode","csv","column","json","parse","format","invalid")):
        return "PARSER_REPAIR_OR_SOURCE_SHAPE"
    if any(x in s for x in ("too large","memory","size","quota","limit")):
        return "BOUNDED_SHARD_OR_BUDGET"
    if any(x in s for x in ("source","identity","winner","player","match","duplicate")):
        return "SOURCE_IDENTITY_OR_CONFLICT"
    return "EXACT_REASON_REQUIRES_REVIEW"

def priority(row):
    name=row["name"];state=row["status"];ext=row["extension"]
    if state=="QUARANTINE":
        # Before increasing ingestion, resolve exact failed files; never turn
        # reason-based priority into a write decision.
        return (0 if row["failure_kind"]=="RETRY_READ_ONLY_DOWNLOAD" else 1)
    if state=="DEFERRED_BUDGET" and ext in (".csv",".tsv",".jsonl"):
        return 2 if MATCH_WORDS.search(name) and RECENT_WORDS.search(name) else 3
    if state=="NEEDS_LARGE_FILE_SHARD":return 4
    if state=="NEEDS_FORMAT_ADAPTER" and ext in (".xls",".xlsx",".json",".sqlite",".csv.gz"):
        return 5
    if state=="DEFERRED_BUDGET":return 6
    if state=="NEEDS_FORMAT_ADAPTER" and ext==".json.gz":
        return 8  # mostly player-level derived charting profiles
    return 7

def build(bundle,expected,out):
    docs=read_verified_bundle(bundle,expected)
    records=json.loads(docs["files.json"])
    report=json.loads(docs["report.json"])
    if not isinstance(records,list) or not isinstance(report,dict):
        raise ValueError("Invalid prior private Drive audit shapes")
    if report.get("cdb_writes")!=0 or report.get("approved_fields")!=0:
        raise ValueError("Original file-status report has nonzero CDB writer side effect")
    inventory={str(x.get("id")):x for x in json.loads(docs.get("drive-inventory.json",b"[]"))
               if isinstance(x,dict) and x.get("id")}
    classified=[];counter=Counter();by_reason=Counter();by_ext=defaultdict(Counter);seen=set()
    for row in records:
        if not isinstance(row,dict) or not row.get("id"):
            raise ValueError("Unusable original source status row")
        status=str(row.get("status") or "")
        counter[status]+=1
        if status not in STATES:continue
        identity=str(row["id"])
        if identity in seen:raise ValueError("Duplicate original Drive file ID in rejected list")
        seen.add(identity)
        name=str(row.get("name") or inventory.get(identity,{}).get("name") or "")
        reason=str(row.get("reason") or "")
        typ=suffix(name)
        item={"schema":1,"drive_file_id":identity,"name":name,
            "source_path":inventory.get(identity,{}).get("path"),
            "source_size_bytes":inventory.get(identity,{}).get("size"),
            "status":status,"reason":reason,
            "failure_kind":reason_kind(reason) if status=="QUARANTINE" else None,
            "extension":typ,"import_ready":False,"canonical_match_id":None,
            "canonical_write_authorized":False,"model_training_authorized":False,
            "source_content_read_this_pass":False}
        item["work_priority"]=priority(item)
        classified.append(item)
        by_ext[status][typ]+=1
        if status=="QUARANTINE":by_reason[item["failure_kind"]]+=1
    classified.sort(key=lambda x:(x["work_priority"],-int(x["source_size_bytes"] or 0),
                                  x["name"],x["drive_file_id"]))
    out.mkdir(parents=True,exist_ok=True)
    path=out/"recovery-work-queue-private.jsonl.gz"
    with path.open("wb") as f:
        with gzip.GzipFile(fileobj=f,filename="",mode="wb",mtime=0,compresslevel=6) as gz:
            with io.TextIOWrapper(gz,encoding="utf-8",newline="\n") as t:
                for row in classified:t.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+"\n")
    quarantine=out/"quarantine-40-private.jsonl"
    with quarantine.open("w",encoding="utf-8") as f:
        for row in classified:
            if row["status"]=="QUARANTINE":f.write(json.dumps(row,sort_keys=True,ensure_ascii=False)+"\n")
    summary={"schema":1,"status":"OLD_REJECTIONS_EXACT_FILE_ID_TRIAGED_NO_SOURCE_REDOWNLOAD",
         "original_bundle_sha256":expected,"original_inventory_files":report.get("inventory_files"),
         "original_readonly_file_status_counts":dict(sorted(counter.items())),
         "rejected_status_count":len(classified),
         "quarantine_count":sum(r["status"]=="QUARANTINE" for r in classified),
         "quarantine_reason_kinds":dict(sorted(by_reason.items())),
         "by_status_extension":{k:dict(sorted(v.items())) for k,v in sorted(by_ext.items())},
         "private_priority_queue_sha256":digest(path.read_bytes()),
         "private_quarantine_sha256":digest(quarantine.read_bytes()),
         "file_status_records_hashed_and_verified":True,
         "individual_raw_source_bytes_newly_reviewed":0,
         "current_CDB_NULL_fields_verified_new":0,
         "canonical_cells_written":0,"sports_api_requests":0,"new_cron":False,
         "important":"Earlier source audit snapshot; this stage is source-file priority only, NOT current CDB or fresh Drive-content verification"}
    (out/"report.json").write_text(json.dumps(summary,sort_keys=True,indent=2)+"\n")
    with (out/"SHA256SUMS").open("w") as f:
        for p in (out/"report.json",path,quarantine):
            f.write(f"{digest(p.read_bytes())}  {p.name}\n")
    return summary

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--prior-archive",required=True,type=Path)
    p.add_argument("--expected-sha256",default=PINNED_BUNDLE_SHA)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    print(json.dumps(build(a.prior_archive,a.expected_sha256,a.out),sort_keys=True))
if __name__=="__main__":main()
