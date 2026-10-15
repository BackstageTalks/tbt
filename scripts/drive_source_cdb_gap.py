#!/usr/bin/env python3
"""Read-only exact snapshot inspection of ATP/WTA CSV sources versus CDB years.

This is an evidence probe, NOT an import, identity crosswalk, or permission to
write. Source match_id differs from canonical match_id unless separately proven.
"""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
from pathlib import Path

FILES = {
 "atp_matches_2025.csv":("atp",2025),
 "atp_matches_2026.csv":("atp",2026),
 "wta_matches_2025.csv":("wta",2025),
 "wta_matches_2026.csv":("wta",2026),
}
DEMOGRAPHIC = ("winner_hand","winner_ht","winner_age","loser_hand","loser_ht","loser_age")
CANONICAL_CANDIDATES = tuple(
  f"{p}{s}" for p in ("player1_","player2_","p1_","p2_")
  for s in ("hand","height","ht","age")
)

def checksum(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda:f.read(1024*1024),b""):
            h.update(part)
    return h.hexdigest()

def read_csv(path):
    stats=Counter()
    ids=set()
    duplicate_ids=0
    with path.open(newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f)
        needed={"match_id","winner_name","loser_name"} | set(DEMOGRAPHIC)
        if not needed.issubset(reader.fieldnames or []):
            raise ValueError("source CSV lacks mandatory fields")
        for row in reader:
            if None in row: raise ValueError("CSV has extra unlabelled columns")
            stats["rows"]+=1
            ident=(row.get("match_id") or "").strip()
            if not ident: raise ValueError("CSV match_id empty")
            if ident in ids:duplicate_ids+=1
            ids.add(ident)
            for field in DEMOGRAPHIC:
                if (row.get(field) or "").strip():
                    stats[field]+=1
    return {"rows":stats["rows"],"unique_source_match_ids":len(ids),
            "duplicate_source_match_ids":duplicate_ids,
            "nonempty_demographic_cells":{x:stats[x] for x in DEMOGRAPHIC},
            "total_nonempty_demographic_cells":sum(stats[x] for x in DEMOGRAPHIC),
            "sha256":checksum(path)}

def read_cdb(path):
    import pyarrow.parquet as pq
    pf=pq.ParquetFile(path)
    schema=pf.schema_arrow
    cols=schema.names
    candidate=[c for c in cols if c in CANONICAL_CANDIDATES]
    totals=Counter()
    for batch in pf.iter_batches(batch_size=16000,columns=candidate):
        for name in candidate:
            col=batch.column(batch.schema.get_field_index(name))
            totals[name]+=len(col)-col.null_count
    return {"rows":pf.metadata.num_rows,"sha256":checksum(path),
            "candidate_fields":{name:{"non_null":totals[name],
                    "null":pf.metadata.num_rows-totals[name]} for name in candidate},
            "schema_field_count":len(cols),
            "all_canonical_field_names":cols,
            "direct_identity_crosswalk_verified":False}

def sidecar(path):
    n=0;key_counts=Counter()
    with gzip.open(path,"rt",encoding="utf8") as f:
        for line in f:
            if not line.strip():continue
            r=json.loads(line)
            if not isinstance(r,dict):raise ValueError("invalid sidecar")
            n+=1
            key_counts.update(r.keys())
    return {"rows":n,"sha256":checksum(path),
            "top_level_keys":dict(key_counts)}

def build(directory):
    src={name:read_csv(directory/name) for name in FILES}
    canonical={str(year):read_cdb(directory/f"history-{year}.parquet") for year in (2025,2026)}
    meta=sidecar(directory/"blinq-uploaded-player-metadata-2025.jsonl.gz")
    manifest=json.loads((directory/"blinq-uploaded-enrichment-manifest.json").read_text(encoding="utf8"))
    counts={"source_rows":sum(x["rows"] for x in src.values()),
            "source_nonempty_demographic_cells":sum(x["total_nonempty_demographic_cells"] for x in src.values()),
            "canonical_2025_rows":canonical["2025"]["rows"],
            "canonical_2026_rows":canonical["2026"]["rows"],
            "already_published_player_metadata_rows_2025":meta["rows"]}
    return {"schema":1,"status":"READ_ONLY_CDB_GAP_PROBE_IDENTITY_NOT_LINKED",
            "source_files":src,"canonical_years":canonical,
            "existing_sidecar":meta,"existing_upload_manifest":manifest,
            "counts":counts,"cdb_import_ready_rows":0,"cdb_writes":0,
            "note":"CSV row fields cannot be matched to canonical match/player IDs by filename or player name. Counts are NOT net-new CDB cells; full identity/provenance/PIT gates required."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    x=p.parse_args()
    report=build(x.input)
    x.out.parent.mkdir(parents=True,exist_ok=True)
    x.out.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf8")
    print(json.dumps({k:v for k,v in report.items() if k in ("status","counts","cdb_writes","cdb_import_ready_rows")},sort_keys=True))

if __name__=="__main__":
    main()
