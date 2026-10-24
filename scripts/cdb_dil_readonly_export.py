"""Read-only private canonical CDB snapshot export for independent DIL parity, never writes CDB."""
from __future__ import annotations
import argparse, datetime, hashlib, json, os, sqlite3, sys
from pathlib import Path
import pyarrow.parquet as pq
import zstandard as zstd
from release_store import ReleaseStore

FIELDS=("match_id","tour","scheduled_at","player1_id","player2_id","winner_id","surface",
        "tournament_id","tournament","round_name","status","stats_json","source_year")
SCHEMA=(
 "match_id TEXT PRIMARY KEY","tour TEXT","scheduled_at INTEGER","player1_id TEXT",
 "player2_id TEXT","winner_id TEXT","surface TEXT","tournament_id TEXT","tournament TEXT",
 "round_name TEXT","status TEXT","stats_json TEXT","source_year INTEGER")
def digest(f):
 h=hashlib.sha256()
 with f.open("rb") as b:
  for chunk in iter(lambda:b.read(8*1024*1024),b""):h.update(chunk)
 return h.hexdigest()
def clean(v,col):
 if v is None:return None
 if col=="scheduled_at":
  if isinstance(v,datetime.datetime):return int(v.timestamp())
  if isinstance(v,str):
   return int(datetime.datetime.fromisoformat(v.replace("Z","+00:00")).timestamp())
  return int(v)
 if col=="stats_json" and isinstance(v,dict):return json.dumps(v,ensure_ascii=False,sort_keys=True)
 if col=="source_year":return int(v)
 return str(v)
def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--repository",required=True)
 ap.add_argument("--out-dir",type=Path,required=True)
 a=ap.parse_args()
 if not os.getenv("GH_TOKEN"):raise SystemExit("Missing private release token")
 a.out_dir.mkdir(parents=True,exist_ok=True)
 history=a.out_dir/"history"
 history.mkdir()
 ReleaseStore(a.repository,"tbt-data-v1",history).download()
 manifest=history/"history_manifest.json"
 if not manifest.exists():raise SystemExit("Missing CDB history manifest")
 files=sorted(history.glob("history-*.parquet"))
 if len(files)<78:raise SystemExit("Incomplete CDB history "+str(len(files)))
 out=a.out_dir/"current_cdb_compare.sqlite"
 con=sqlite3.connect(out)
 con.execute("PRAGMA journal_mode=OFF")
 con.execute("PRAGMA synchronous=OFF")
 con.execute("CREATE TABLE cdb_matches("+",".join(SCHEMA)+") WITHOUT ROWID")
 con.execute("CREATE TABLE receipt(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
 year_counts={}
 total=0
 for f in files:
  reader=pq.ParquetFile(f)
  present=set(reader.schema_arrow.names)
  if not set(FIELDS).issubset(present):
   raise SystemExit("CDB schema lacks "+str(set(FIELDS)-present)+" in "+f.name)
  count=0
  for batch in reader.iter_batches(batch_size=4096,columns=list(FIELDS)):
   values=batch.to_pydict()
   rows=[tuple(clean(v,col) for col,v in zip(FIELDS,vals)) for vals in zip(*(values[c] for c in FIELDS))]
   con.executemany("INSERT INTO cdb_matches VALUES ("+",".join("?" for _ in FIELDS)+")",rows)
   count+=len(rows)
  con.commit()
  total+=count
  year_counts[f.name]=count
 snap=json.loads(manifest.read_text())
 con.execute("INSERT INTO receipt VALUES(?,?)",("manifest_sha256",digest(manifest)))
 con.execute("INSERT INTO receipt VALUES(?,?)",("year_counts",json.dumps(year_counts,sort_keys=True)))
 con.execute("INSERT INTO receipt VALUES(?,?)",("scope","tbt-data-v1 SHA verified private CDB read-only"))
 con.execute("INSERT INTO receipt VALUES(?,?)",("release_tag","tbt-data-v1"))
 con.commit()
 check=con.execute("PRAGMA quick_check").fetchone()[0]
 if check!="ok":raise SystemExit("CDB shadow invalid: "+str(check))
 readback=con.execute("SELECT COUNT(*),COUNT(DISTINCT match_id) FROM cdb_matches").fetchone()
 if readback!=(total,total):raise SystemExit("CDB shadow invalid count "+str(readback))
 con.close()
 z=a.out_dir/"current_cdb_compare.sqlite.zst"
 with out.open("rb") as src,z.open("wb") as dst:
  zstd.ZstdCompressor(level=8,threads=2).copy_stream(src,dst)
 report={"status":"VERIFIED_CDB_READONLY_EXPORT","release":"tbt-data-v1",
  "history_parts":len(files),"rows":total,
  "manifest_sha256":digest(manifest),
  "compressed_sha256":digest(z),
  "compressed_bytes":z.stat().st_size,"quick_check":check,
  "cdb_written":False,"dil_written":False,
  "by_year":year_counts}
 (a.out_dir/"cdb_compare_receipt.json").write_text(json.dumps(report,indent=2))
 print(json.dumps({k:v for k,v in report.items() if k!="by_year"}))
if __name__=="__main__":main()
