#!/usr/bin/env python3
"""Read-only, SHA-pinned input staging preflight for BlinQ identity-v2.

Supports source-native match CSV/JSONL with separate adapters. Only emits
aggregate JSON to stdout. Never queries API, CDB, writes data, or imports.
The caller must supply the *actual* source format and expected raw SHA.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import re

from scripts.research import identity_v2_adapters as a

ADAPTERS = {"sackmann", "season", "canonical"}
FORMATS = {"csv", "jsonl"}


def file_hash(file: Path) -> str:
    h=sha256()
    with file.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576),b""):
            h.update(block)
    return h.hexdigest()


def stream_rows(path: Path, fmt: str):
    with path.open(encoding="utf-8-sig",newline="") as stream:
        if fmt=="csv":
            for lineno,row in enumerate(csv.DictReader(stream),2):
                yield lineno,row
        elif fmt=="jsonl":
            for lineno,line in enumerate(stream,1):
                if not line.strip():
                    continue
                obj=json.loads(line,
                   parse_constant=lambda _: (_ for _ in ()).throw(
                       ValueError("Nonfinite JSON literal")))
                if not isinstance(obj,dict):
                    raise ValueError("JSONL records must be objects")
                yield lineno,obj
        else:
            raise ValueError("Explicit supported input format required")


def stage_readonly(path: Path, *, expected_sha: str, kind: str,
                   fmt: str, tour: str="", collection: str="",
                   max_rows: int=100000):
    if kind not in ADAPTERS or fmt not in FORMATS:
        raise ValueError("Unsupported explicit source family or format")
    if not re.fullmatch(r"[a-f0-9]{64}",expected_sha):
        raise ValueError("A valid SHA-256 file fingerprint is required")
    if not path.is_file() or file_hash(path)!=expected_sha:
        raise ValueError("SOURCE_SHA_GATE_FAILED")
    if not 1<=max_rows<=1000000:
        raise ValueError("Rows limit must be 1..1000000")
    if kind in ("sackmann","season") and (tour not in ("atp","wta") or not collection):
        raise ValueError("Native sources require tour and collection")
    counts=Counter()
    seen=set()
    for lineno,row in stream_rows(path,fmt):
        counts["input_rows"]+=1
        if counts["input_rows"]>max_rows:
            raise ValueError("INPUT_MAX_ROWS_EXCEEDED: no partial acceptance")
        if kind=="sackmann":
            result=a.from_sackmann(row,tour=tour,collection=collection,
                                    file_sha256=expected_sha,line_number=lineno)
        elif kind=="season":
            result=a.from_season(row,tour=tour,collection=collection,
                                 file_sha256=expected_sha,line_number=lineno)
        else:
            result=a.from_cdb_metadata(row)
        result=a.require_source_only(result)
        if result.event is None:
            counts["quarantine_rows"]+=1
            for reason in result.reasons:
                counts["blocked_"+reason]+=1
            continue
        key=(result.source_namespace,result.source_native_key)
        if key in seen:
            counts["duplicate_native_event_key_quarantined"]+=1
            counts["quarantine_rows"]+=1
            continue
        seen.add(key)
        counts["source_only_normalized_events"]+=1
        counts["tour_"+result.event.tour]+=1
        counts["date_kind_"+result.event.date_kind]+=1
    if not counts["input_rows"]:
        raise ValueError("ZERO_ROWS: no staging possible")
    return {
        "schema":"BLINQ_IDENTITY_V2_RAW_SOURCE_PREFLIGHT_V1",
        "input_sha256":expected_sha,
        "explicit_format":fmt,
        "source_kind":kind,
        "tour":tour,
        "source_collection":collection,
        "counts":dict(sorted(counts.items())),
        "independently_verified_canonical_events":0,
        "independently_verified_player_ID_links":0,
        "cdb_import_authorized":False,
        "cdb_writes":0,
        "reason":"Source-only normalization, not canonical ID proof, field rights or fresh NULL delta",
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",required=True,type=Path)
    parser.add_argument("--source-sha256",required=True)
    parser.add_argument("--format",choices=sorted(FORMATS),required=True)
    parser.add_argument("--kind",choices=sorted(ADAPTERS),required=True)
    parser.add_argument("--tour",choices=("atp","wta"),default="")
    parser.add_argument("--collection",default="")
    parser.add_argument("--max-rows",type=int,default=100000)
    opts=parser.parse_args()
    report=stage_readonly(opts.source,expected_sha=opts.source_sha256,
       kind=opts.kind,fmt=opts.format,tour=opts.tour,
       collection=opts.collection,max_rows=opts.max_rows)
    print(json.dumps(report,sort_keys=True,allow_nan=False))


if __name__=="__main__":
    main()
