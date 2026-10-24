"""Persist every private-training Parquet row/column in a typed, isolated SQLite SOURCE layer."""
import argparse, base64, datetime, decimal, hashlib, json, sqlite3
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import zstandard as zstd

def digest(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b""): h.update(chunk)
    return h.hexdigest()
def quote(x): return '"' + x.replace('"','""') + '"'
def typ(t):
    return "INTEGER" if pa.types.is_boolean(t) or pa.types.is_integer(t) else ("REAL" if pa.types.is_floating(t) else "TEXT")
def convert(v):
    if v is None:return None
    if isinstance(v,bool):return int(v)
    if isinstance(v,(int,float,str)):return v
    if isinstance(v,(datetime.datetime,datetime.date,datetime.time)):return v.isoformat()
    if isinstance(v,decimal.Decimal):return str(v)
    if isinstance(v,bytes):return 'base64:'+base64.b64encode(v).decode()
    return json.dumps(v,sort_keys=True,ensure_ascii=False,default=str)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-dir",type=Path,required=True)
    p.add_argument("--out-dir",type=Path,required=True)
    a=p.parse_args()
    a.out_dir.mkdir(parents=True,exist_ok=True)
    f=a.source_dir/"training_table.parquet"
    metadata=json.loads((a.source_dir/"training_table_report.json").read_text())
    receipt=json.loads((a.source_dir/"dil_training_source_receipt.json").read_text())
    if digest(f)!=receipt["files"]["training_table.parquet"]["sha256"]: raise SystemExit("Source digest mismatch")
    pf=pq.ParquetFile(f)
    expected=int(metadata["rows"])
    if pf.metadata.num_rows!=expected or len(pf.schema_arrow)!=156:raise SystemExit("Unexpected rows/columns")
    fields=list(pf.schema_arrow)
    names=[x.name for x in fields]
    if len(names)!=len(set(x.casefold() for x in names)):raise SystemExit("Ambiguous column names")
    db=a.out_dir/"dil_training_all_source.sqlite"
    if db.exists(): db.unlink()
    con=sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("CREATE TABLE training_source_records(source_row_number INTEGER PRIMARY KEY,"+
      ",".join(quote(x.name)+" "+typ(x.type) for x in fields)+")")
    con.execute("CREATE TABLE source_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    con.executemany("INSERT INTO source_metadata VALUES(?,?)",[
      ("source_release","tbt-training-table-v1"),
      ("parquet_sha256",digest(f)),
      ("rows_expected",str(expected)),
      ("columns_json",json.dumps([{"name":x.name,"arrow_type":str(x.type),"sqlite_type":typ(x.type)} for x in fields])),
      ("semantics","SOURCE_ONLY: training features and labels are not canonical stats; no pre-match promotion")])
    insert="INSERT INTO training_source_records VALUES("+",".join(["?"]*(len(names)+1))+")"
    n=0
    samples={}
    for batch in pf.iter_batches(batch_size=2500):
        rows=[]
        for item in batch.to_pylist():
            n+=1
            vals=tuple(convert(item[c]) for c in names)
            rows.append((n,*vals))
            if n in (1,expected//2,expected): samples[n]=vals
        con.executemany(insert,rows)
        if n%50000<len(rows):con.commit()
    con.commit()
    observed=con.execute("SELECT COUNT(*),MIN(source_row_number),MAX(source_row_number) FROM training_source_records").fetchone()
    if observed!=(expected,1,expected):raise SystemExit("Training table row-count mismatch "+repr(observed))
    sample_ok=all(con.execute("SELECT * FROM training_source_records WHERE source_row_number=?",(k,)).fetchone()[1:]==v for k,v in samples.items())
    if not sample_ok:raise SystemExit("Sample read-back failure")
    integrity=con.execute("PRAGMA quick_check").fetchone()[0]
    if integrity!="ok":raise SystemExit("Source SQLite quick_check failed "+integrity)
    con.close()
    dst=a.out_dir/"dil_training_all_source.sqlite.zst"
    with db.open("rb") as inp,dst.open("wb") as out:
        zstd.ZstdCompressor(level=6,threads=2).copy_stream(inp,out)
    receipt_out={"status":"verified_source_layer_not_canonical",
       "source_release":"tbt-training-table-v1","source_parquet_sha256":digest(f),
       "rows":observed[0],"columns":len(names),"sqlite_quick_check":integrity,"sample_readback_ok":sample_ok,
       "source_sqlite_size":db.stat().st_size,"compressed_size":dst.stat().st_size,
       "compressed_sha256":digest(dst),"production_cdb_modified":False,"main_dil_modified":False}
    (a.out_dir/"dil_training_source_export_receipt.json").write_text(json.dumps(receipt_out,indent=2))
    print(json.dumps(receipt_out))
if __name__=="__main__":main()
