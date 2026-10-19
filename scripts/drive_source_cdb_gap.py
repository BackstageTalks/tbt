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
import math
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
STAT_FIELDS = tuple(f"{side}_{field}" for side in ("p1", "p2") for field in (
    "aces", "double_faults", "first_serve_win", "second_serve_win",
    "service_points_won", "return_points_won", "break_point_serve_win",
    "break_point_return_win"))

def missing_stats(raw):
    """Absent keys and explicit NULL are gaps; zero remains an observation."""
    stats = {} if raw is None or raw == "" else json.loads(raw)
    if not isinstance(stats, dict):
        raise ValueError("Canonical stats_json is not an object")
    for key in STAT_FIELDS:
        value = stats.get(key)
        if value is not None and (isinstance(value, bool) or
                not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError("Invalid canonical numeric statistic")
    return [key for key in STAT_FIELDS if stats.get(key) is None]

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
    field_counts=Counter()
    with path.open(newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f)
        needed={"match_id","winner_name","loser_name"} | set(DEMOGRAPHIC)
        if not needed.issubset(reader.fieldnames or []):
            raise ValueError("source CSV lacks mandatory fields")
        for row in reader:
            if None in row: raise ValueError("CSV has extra unlabelled columns")
            stats["rows"]+=1
            field_counts.update(k for k,v in row.items() if (v or "").strip())
            ident=(row.get("match_id") or "").strip()
            if not ident: raise ValueError("CSV match_id empty")
            if ident in ids:duplicate_ids+=1
            ids.add(ident)
            for field in DEMOGRAPHIC:
                if (row.get(field) or "").strip():
                    stats[field]+=1
    return {"rows":stats["rows"],"unique_source_match_ids":len(ids),
            "duplicate_source_match_ids":duplicate_ids,
            "nonempty_source_fields":dict(sorted(field_counts.items())),
            "nonempty_demographic_cells":{x:stats[x] for x in DEMOGRAPHIC},
            "total_nonempty_demographic_cells":sum(stats[x] for x in DEMOGRAPHIC),
            "sha256":checksum(path)}

def read_cdb(path, null_output=None):
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
    required = ["match_id", "tour", "status", "player1_id", "player2_id", "stats_json"]
    if not set(required).issubset(cols):
        raise ValueError("Canonical identity/statistics schema missing")
    gaps=Counter(); finished_gaps=Counter(); cohorts=Counter(); seen=set(); null_rows=0
    for batch in pf.iter_batches(batch_size=16000, columns=required):
        for row in batch.to_pylist():
            mid=row["match_id"]
            if not isinstance(mid,str) or not mid or mid in seen:
                raise ValueError("Empty or duplicate canonical match ID")
            seen.add(mid)
            tour=str(row["tour"] or "").lower()
            if tour not in ("atp", "wta"):
                continue
            status=str(row["status"] or "").lower()
            missing=missing_stats(row["stats_json"])
            cohorts[tour+":"+status]+=1
            gaps.update(missing)
            if status in ("finished", "completed", "ended"):
                finished_gaps.update(missing)
            if missing:
                null_rows+=1
                if null_output is not None:
                    null_output.write(json.dumps({"match_id":mid,"tour":tour,"status":status,
                        "player1_id":row["player1_id"],"player2_id":row["player2_id"],
                        "partition":path.name,"missing_fields":missing,
                        "import_ready":False},sort_keys=True)+"\n")
    return {"rows":pf.metadata.num_rows,"sha256":checksum(path),
            "candidate_fields":{name:{"non_null":totals[name],
                    "null":pf.metadata.num_rows-totals[name]} for name in candidate},
            "schema_field_count":len(cols),
            "stat_null_cells":dict(sorted(gaps.items())),
            "completed_stat_null_cells":dict(sorted(finished_gaps.items())),
            "matches_with_stat_gaps":null_rows,"cohort_rows":dict(sorted(cohorts.items())),
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

def build(directory, null_dir=None):
    src={name:read_csv(directory/name) for name in FILES}
    canonical={}
    for year in (2025,2026):
        if null_dir is None:
            canonical[str(year)]=read_cdb(directory/f"history-{year}.parquet")
        else:
            null_dir.mkdir(parents=True,exist_ok=True)
            output=null_dir/f"canonical-null-cells-{year}.jsonl.gz"
            with gzip.open(output,"wt",encoding="utf8") as stream:
                canonical[str(year)]=read_cdb(directory/f"history-{year}.parquet",stream)
            canonical[str(year)]["private_null_manifest_sha256"]=checksum(output)
    meta=sidecar(directory/"blinq-uploaded-player-metadata-2025.jsonl.gz")
    manifest=json.loads((directory/"blinq-uploaded-enrichment-manifest.json").read_text(encoding="utf8"))
    counts={"source_rows":sum(x["rows"] for x in src.values()),
            "source_nonempty_demographic_cells":sum(x["total_nonempty_demographic_cells"] for x in src.values()),
            "canonical_2025_rows":canonical["2025"]["rows"],
            "canonical_2026_rows":canonical["2026"]["rows"],
            "already_published_player_metadata_rows_2025":meta["rows"]}
    counts["stat_null_cells_by_year"]={year:data["stat_null_cells"] for year,data in canonical.items()}
    counts["completed_stat_null_cells_by_year"]={year:data["completed_stat_null_cells"] for year,data in canonical.items()}
    counts["source_field_coverage"]={name:data["nonempty_source_fields"] for name,data in src.items()}
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
    report=build(x.input,x.out.parent/"private-null-cells")
    x.out.parent.mkdir(parents=True,exist_ok=True)
    x.out.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf8")
    print(json.dumps({k:v for k,v in report.items() if k in ("status","counts","cdb_writes","cdb_import_ready_rows")},sort_keys=True))

if __name__=="__main__":
    main()

