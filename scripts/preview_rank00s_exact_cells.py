"""Isolated, read-only-input preview of SHA-pinned ATP 2000-2009 NULL rank fills.

Consumes reviewed-but-NOT-APPROVED preflight stage. Creates preview-prefixed
Parquet files in a new isolated directory, never canonical release names.
This cannot authorize or execute a live CDB write.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path

SOURCE_CSV_SHA = "1d17593dcb12df7df6916892049ca5d0f0e1b4d874df77421e0c65967467094a"
MANIFEST_SHA = "ac33267d6d51f5e36c1ad2efc2134fad5155f347044bdb40d24ef94d68b2f984"
PARTITIONS = {
    2000:("224181d0a498b634bc058e0cf9e8d188dfc14c779fe5990cd6365442c618e022",1168710),
    2001:("2e8e051eaeffc9faa9e596fc5fdcca534b5f054094fd110cae5ae13ab51eb1d9",1263792),
    2002:("4f0c1b6e5663e2b3570ddc77f638a10b73203cac36ddd1971b08f073c96ad8ba",1186985),
    2003:("35a71fb0c922f2ddcd435bc469c0f03f2f1e218dfd28bf094888f9b550b7e75a",1196655),
    2004:("3b620cb493ea75824bc0c229c473030b0c120729a3d782fe3b6df822fca9842a",1250423),
    2005:("382a91568211641f03ae4bd69f713f99266a53d187333db928c45e96788cc9a3",1284100),
    2006:("07ab9cb72b85265a47433a3e150bf2c0adf93576793682e1fc21d657f985462e",1385073),
    2007:("6c42083466fd503415d05e3054b11903b5f09c880d9a9ec94e8ef73b33772e82",1695985),
    2008:("44e241f0e2163bd6c7562d5917479b2b67334907e7d67a3894e4b1e4e51f520f",1802033),
    2009:("1fcaacc59262ebc8a09e35988bf52359cd53af3ce76c7a6c13f30de64735fa5",2075887),
}
FIELDS = {"player1_rank": "player1_id", "player2_rank": "player2_id"}
REQUIRED = {"match_id","tour","scheduled_at","player1_id","player2_id",
            "player1_rank","player2_rank"}

class Blocked(ValueError):
    """Fail closed: no canonical production write permitted."""

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1<<20),b""):
            h.update(chunk)
    return h.hexdigest()

def pins(canonical_dir):
    root=Path(canonical_dir)
    if sha256(root/"history_manifest.json")!=MANIFEST_SHA:
        raise Blocked("Stale/missing canonical manifest")
    for year,(expected_sha,expected_size) in PARTITIONS.items():
        p=root/f"history-{year}.parquet"
        if p.stat().st_size!=expected_size or sha256(p)!=expected_sha:
            raise Blocked(f"Stale/missing canonical partition {year}")

def stage(report_file,candidates_file):
    report=json.loads(Path(report_file).read_text(encoding="utf8"))
    if (report.get("state")!="PREPARED_READONLY_NO_CDB_WRITE"
        or report.get("safe_for_production_write") is not False
        or report.get("canonical_writes")!=0
        or report.get("history_manifest_sha256")!=MANIFEST_SHA
        or report.get("source_counts",{}).get("rows")!=920907
        or report.get("source_counts",{}).get("missing_points")!=516
        or report.get("stage_sha256")!=sha256(candidates_file)):
        raise Blocked("Source preflight report is stale or unsafe")
    out=[]; seen=set()
    with Path(candidates_file).open(encoding="utf8") as f:
        for raw in f:
            if not raw.strip():
                continue
            if len(out)>=2_000_000:
                raise Blocked("Source stage exceeds bound")
            row=json.loads(raw,parse_constant=lambda x:(_ for _ in ()).throw(Blocked(x)))
            if not isinstance(row,dict):
                raise Blocked("Non-object source candidate")
            mid=row.get("match_id"); field=row.get("field")
            year=row.get("canonical_year"); key=(mid,field)
            if (not isinstance(mid,str) or not mid or field not in FIELDS
                or type(year) is not int or year not in PARTITIONS or key in seen
                or row.get("status")!="REVIEW_ONLY_NO_WRITE"
                or row.get("expected_current_value",object()) is not None
                or row.get("source_csv_sha256")!=SOURCE_CSV_SHA
                or row.get("source_baseline_history_manifest_sha256")!=MANIFEST_SHA
                or row.get("canonical_partition_sha256")!=PARTITIONS[year][0]
                or row.get("tour")!="atp"):
                raise Blocked("Invalid, duplicate or unpinned candidate")
            if any(not isinstance(row.get(k),str) or not row[k].strip()
                   for k in ("canonical_player1_id","canonical_player2_id","source_player_id")):
                raise Blocked("Missing canonical player IDs")
            if row["canonical_player1_id"]==row["canonical_player2_id"]:
                raise Blocked("Both canonical players collapse to same ID")
            if (not row["source_player_id"].isascii()
                or not row["source_player_id"].isdecimal()
                or row["source_player_id"]=="104711"):
                raise Blocked("Invalid source namespace ID")
            rank=row.get("candidate_value")
            if type(rank) is not int or not 1<=rank<=30000:
                raise Blocked("Invalid candidate ranking value")
            try:
                source_date=date.fromisoformat(row["source_date"])
            except (KeyError,TypeError,ValueError) as e:
                raise Blocked("Invalid source PIT day") from e
            if not 1999<=source_date.year<=2009:
                raise Blocked("Unexpected source ranking year")
            seen.add(key);out.append(row)
    if not out or report.get("candidate_cells")!=len(out):
        raise Blocked("Missing candidates or stage/report count drift")
    return out

def _day(value):
    import pandas as pd
    try:
        timestamp=pd.Timestamp(value)
    except (ValueError,TypeError) as e:
        raise Blocked("Invalid match timestamp") from e
    if timestamp.tzinfo is None:
        raise Blocked("Naive match timestamp")
    return timestamp.tz_convert("UTC").date()

def _absent(value):
    import pandas as pd
    return value is None or (not isinstance(value,(list,dict)) and bool(pd.isna(value)))

def preview(frames,candidates):
    """Exact in-memory patch, with full untouched-cell and identity checks."""
    import pandas as pd
    out={int(y):frame.copy(deep=True) for y,frame in frames.items()}
    indices={}
    for year,frame in frames.items():
        if not REQUIRED.issubset(frame.columns):
            raise Blocked("Canonical schema missing ranking columns")
        ids=frame["match_id"].astype(str)
        if ids.duplicated().any() or (ids=="").any():
            raise Blocked("Duplicate/empty canonical match identity")
        indices[int(year)]={mid:i for mid,i in zip(ids,frame.index)}
    counts=Counter(); seen=set()
    for row in candidates:
        year=int(row["canonical_year"]);mid=row["match_id"];field=row["field"]
        if year not in frames or mid not in indices[year] or (mid,field) in seen:
            raise Blocked("Candidate absent/duplicated in canonical partition")
        idx=indices[year][mid]; old=frames[year].loc[idx]
        if (str(old["tour"]).lower()!="atp"
            or _day(old["scheduled_at"]).year!=year
            or str(old["player1_id"])!=row["canonical_player1_id"]
            or str(old["player2_id"])!=row["canonical_player2_id"]):
            raise Blocked("Canonical match tour/year/player orientation drift")
        age=(_day(old["scheduled_at"])-date.fromisoformat(row["source_date"])).days
        if not 1<=age<=14:
            raise Blocked("Rank snapshot not strictly before match within 14 days")
        if not _absent(old[field]):
            raise Blocked("No NULL CAS: existing canonical rank must never overwrite")
        out[year].at[idx,field]=row["candidate_value"]
        seen.add((mid,field));counts["candidate_cells"]+=1
        counts[f"year_{year}_cells"]+=1
    for year in frames:
        changed={mid for mid,field in seen if mid in indices[year]}
        before=frames[year];after=out[year]
        pd.testing.assert_frame_equal(before.drop(columns=list(FIELDS)),
                                      after.drop(columns=list(FIELDS)),check_dtype=True)
        untouched=~before["match_id"].astype(str).isin(changed)
        pd.testing.assert_frame_equal(before.loc[untouched],after.loc[untouched],check_dtype=True)
    return out,dict(counts)

def run(canonical_dir,report_path,candidates_path,output_dir):
    """Output is preview-prefix only, in a new isolated directory."""
    import pandas as pd
    canonical_dir=Path(canonical_dir).resolve()
    output_dir=Path(output_dir).resolve()
    if (output_dir==canonical_dir or canonical_dir in output_dir.parents
        or output_dir in canonical_dir.parents or output_dir.exists()):
        raise Blocked("Preview output must be NEW and isolated from canonical CDB")
    pins(canonical_dir)
    rows=stage(report_path,candidates_path)
    years=sorted({row["canonical_year"] for row in rows})
    frames={year:pd.read_parquet(canonical_dir/f"history-{year}.parquet") for year in years}
    patched,counts=preview(frames,rows)
    pins(canonical_dir)
    output_dir.mkdir(parents=True,exist_ok=False)
    summary={"state":"ISOLATED_PREVIEW_NOT_AUTHORIZED_FOR_PRODUCTION",
             "safe_for_production_write":False,"production_mutated":False,
             "source_manifest_sha256":MANIFEST_SHA,"source_csv_sha256":SOURCE_CSV_SHA,
             "affected_years":years,"counts":counts,"isolated_files":{}}
    for year in years:
        p=output_dir/f"preview-history-{year}.parquet"
        patched[year].to_parquet(p,engine="pyarrow",compression="zstd",index=False)
        readback=pd.read_parquet(p)
        pd.testing.assert_frame_equal(readback,patched[year].reset_index(drop=True),
                                      check_dtype=True)
        summary["isolated_files"][str(year)]={"filename":p.name,"sha256":sha256(p),"rows":len(readback)}
    (output_dir/"NOT_FOR_CDB_RELEASE.txt").write_text(
        "ISOLATED NULL-only PREVIEW. NOT FOR PRODUCTION CDB RELEASE.\n",encoding="utf8")
    (output_dir/"preview_report.json").write_text(
        json.dumps(summary,sort_keys=True,indent=2)+"\n",encoding="utf8")
    return summary

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("canonical-dir","preflight-report","candidates","output-dir"):
        p.add_argument("--"+name,type=Path,required=True)
    args=p.parse_args()
    result=run(args.canonical_dir,args.preflight_report,args.candidates,args.output_dir)
    print(json.dumps({"state":result["state"],"counts":result["counts"],
                      "safe_for_production_write":False},sort_keys=True))

if __name__=="__main__":
    main()
