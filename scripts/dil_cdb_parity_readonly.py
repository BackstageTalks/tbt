"""Read-only, pinned CDB census and exact-match comparison index for DIL parity."""
from __future__ import annotations
import argparse
from collections import Counter
from pathlib import Path
import hashlib
import json
import os
import re
import sqlite3
import time

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(4*1024*1024), b""): h.update(chunk)
    return h.hexdigest()

def main():
    import pyarrow.parquet as pq
    import zstandard as zstd
    from download_stable_cdb import download_stable

    a=argparse.ArgumentParser()
    a.add_argument("--repo",required=True)
    a.add_argument("--out",type=Path,required=True)
    x=a.parse_args()
    x.out.mkdir(parents=True,exist_ok=True)
    report=download_stable(x.repo,"tbt-data-v1",x.out/"canonical-history")
    root=x.out/"canonical-history"
    manifest=json.loads((root/"history_manifest.json").read_text())
    years=manifest["years"]
    ix=x.out/"cdb_matchlevel_compare.sqlite"
    db=sqlite3.connect(ix)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.execute("""CREATE TABLE cdb_matches(
        match_id TEXT PRIMARY KEY,
        tour TEXT,
        source_year INTEGER,
        scheduled_at TEXT,
        player1_id TEXT, player2_id TEXT, winner_id TEXT,
        status TEXT,surface TEXT,tournament TEXT,stats_json TEXT,
        player1_rank TEXT,player2_rank TEXT
    ) WITHOUT ROWID""")
    rowcount=0
    by_year_tour=Counter()
    by_status=Counter()
    notnull=Counter()
    statskeys=Counter()
    stats_nonempty=0
    raw_metric_values=0
    by_year_stat=Counter()
    for year, meta in sorted(years.items(),key=lambda z:int(z[0])):
        name=meta.get("asset") or f"history-{int(year):04d}.parquet"
        f=root/name
        pf=pq.ParquetFile(f)
        cols=set(pf.schema_arrow.names)
        if not {"match_id","tour","stats_json"}.issubset(cols):
            raise SystemExit("Required CDB columns unavailable: "+name)
        wanted=["match_id","tour","scheduled_at","player1_id","player2_id","winner_id",
                "status","surface","tournament","stats_json","player1_rank","player2_rank"]
        selected=[t for t in wanted if t in cols]
        year_rows=0
        for batch in pf.iter_batches(batch_size=4000,columns=selected):
            buffer=[]
            for item in batch.to_pylist():
                rowcount+=1
                year_rows+=1
                mid=str(item["match_id"])
                tour=str(item["tour"]).lower()
                by_year_tour[(year,tour)]+=1
                by_status[str(item.get("status") or "")]+=1
                for field in wanted:
                    if field!="stats_json" and item.get(field) is not None:
                        notnull[field]+=1
                raw=item.get("stats_json")
                if raw is None or raw=="":
                    stats={}
                elif isinstance(raw,dict):stats=raw
                else:
                    stats=json.loads(raw)
                if not isinstance(stats,dict):raise SystemExit("Invalid CDB stats object")
                populated={k:v for k,v in stats.items() if v is not None}
                raw_metric_values+=len(populated)
                if populated:
                    stats_nonempty+=1
                    by_year_stat[year]+=1
                statskeys.update(populated.keys())
                record=(mid,tour,int(year))
                remain=[]
                for field in wanted[2:]:
                    val=item.get(field)
                    if field=="stats_json":
                        val=json.dumps(stats,sort_keys=True,separators=(",",":"),ensure_ascii=False)
                    elif val is not None:
                        val=str(val)
                    remain.append(val)
                buffer.append(record+tuple(remain))
            db.executemany("INSERT INTO cdb_matches VALUES("+",".join("?" for _ in range(13))+")",buffer)
        if int(meta.get("rows") or year_rows)!=year_rows:
            raise SystemExit("Year manifest row count inconsistent: "+year)
        db.commit()
    observed=db.execute("SELECT COUNT(*) FROM cdb_matches").fetchone()[0]
    if observed!=rowcount:
        raise SystemExit("Duplicate canonical CDB identities")
    index_integrity=db.execute("PRAGMA quick_check").fetchone()[0]
    if index_integrity!="ok":raise SystemExit("Index integrity fail "+str(index_integrity))
    db.close()
    packed=x.out/"cdb_matchlevel_compare.sqlite.zst"
    with ix.open("rb") as src, packed.open("wb") as dst:
        zstd.ZstdCompressor(level=7,threads=2).copy_stream(src,dst)
    manifest_after=sha(root/"_tbt_bundle_manifest.json")
    if manifest_after!=report["manifest_sha256"]:
        raise SystemExit("Manifest changed during CDB scan")
    summary={
        "schema":"cdb-dil-parity-readonly-20261024-v1",
        "status":"VERIFIED_READONLY_CDB_SNAPSHOT",
        "release_tag":"tbt-data-v1",
        "canonical_snapshot_bundle_sha256":report["manifest_sha256"],
        "history_manifest_sha256":sha(root/"history_manifest.json"),
        "rows":rowcount,
        "stats_json_nonempty_matches":stats_nonempty,
        "populated_stats_json_values":raw_metric_values,
        "by_year_tour":{f"{y}:{tour}":n for (y,tour),n in sorted(by_year_tour.items())},
        "stats_nonempty_by_year":dict(sorted(by_year_stat.items())),
        "statuses":dict(sorted(by_status.items())),
        "non_null_fields":dict(sorted(notnull.items())),
        "stats_key_counts":dict(sorted(statskeys.items())),
        "parquet_assets_scanned":len(years),
        "cdb_index_sha256":sha(packed),
        "cdb_index_compressed_size":packed.stat().st_size,
        "cdb_index_integrity":index_integrity,
        "production_writes":0
    }
    (x.out/"cdb_dil_parity_cdb_report.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({"status":summary["status"],"rows":rowcount,"metric_values":raw_metric_values,
                     "years":len(years),"archive_sha256":sha(packed)}))

if __name__=="__main__":
    main()
