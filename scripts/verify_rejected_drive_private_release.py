#!/usr/bin/env python3
"""Independently validate immutable private rejected-source Release without re-fetching Drive.

GitHub Release asset names are sanitized; original file SHA and its exact
name are recovered using the previously SHA-verified private manifest.
Never mutate source or CDB; this changes only a disposable local directory.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

WTA_ORIGINAL="WTA Tennis 2007 - 2026 Daily update.xlsx"
WTA_GITHUB_ASSET="WTA.Tennis.2007.-.2026.Daily.update.xlsx"
ATP="atp_tennis2.txt"

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def verify(folder:Path):
    report_file=folder/"report.json"
    sums=folder/"SHA256SUMS"
    raw=folder/WTA_ORIGINAL
    normalized=folder/WTA_GITHUB_ASSET
    if not report_file.is_file() or not sums.is_file():
        raise ValueError("Missing report or checksum manifest")
    report=json.loads(report_file.read_text())
    if (report.get("schema")!=1
            or report.get("status")!="REJECTED_DRIVE_SOURCE_ROWS_RETAINED_PRIVATE_NO_CDB_WRITE"
            or report.get("source_rows")!=114143
            or report.get("canonical_cells_written")!=0
            or report.get("canonical_matches_proven")!=0
            or report.get("accepted_source_matches_eligible_for_cdb")!=0
            or report.get("sports_api_requests")!=0):
        raise ValueError("Untrusted private evidence report contract")
    if raw.exists() and normalized.exists():
        raise ValueError("Conflicting original/sanitized XLSX asset names")
    if not raw.exists():
        if not normalized.is_file():
            raise FileNotFoundError("Missing immutable WTA asset")
        normalized.rename(raw)
    expected={
        "report.json":sha(report_file),
        "rejected-source-observations.jsonl.gz":report["observations_sha256"],
        ATP:report["by_tour"]["atp"]["sha256"],
        WTA_ORIGINAL:report["by_tour"]["wta"]["sha256"],
    }
    listed={}
    for line in sums.read_text().splitlines():
        bits=line.split("  ",1)
        if len(bits)!=2 or bits[1] in listed or bits[1] not in expected:
            raise ValueError("Duplicate/unsupported SHA256SUMS asset")
        listed[bits[1]]=bits[0]
    if listed != expected:
        raise ValueError("Exact original source checksum manifest differs")
    for filename,digest in expected.items():
        p=folder/filename
        if not p.is_file() or sha(p)!=digest:
            raise ValueError("Private persisted SHA256 mismatch: "+filename)
    n=0
    total=0
    with gzip.open(folder/"rejected-source-observations.jsonl.gz","rt",encoding="utf-8") as f:
        for line in f:
            x=json.loads(line)
            if (x.get("schema")!=1 or x.get("canonical_match_id") is not None
                    or x.get("canonical_write_authorized") is not False
                    or x.get("import_ready") is not False
                    or x.get("model_use_authorized") is not False
                    or x.get("source_tour") not in ("atp","wta")):
                raise ValueError("Untrusted source-only persisted observation")
            n+=1
            if x["source_tour"]=="atp":total+=1
    if n!=114143 or total!=68760 or n-total!=45383:
        raise ValueError("Remote archive observation counts do not match origin")
    return {"schema":1,"status":"INDEPENDENT_PRIVATE_RELEASE_READBACK_PASS",
            "rows":n,"atp":total,"wta":n-total,"raw_file_sha256_verified":2,
            "private_release_asset_bytes_verified":len(expected),
            "canonical_cells_written":0,"sports_api_requests":0}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--release-download-dir",required=True,type=Path)
    args=p.parse_args()
    print(json.dumps(verify(args.release_download_dir),sort_keys=True))
if __name__=="__main__":main()
