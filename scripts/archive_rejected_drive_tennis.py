#!/usr/bin/env python3
"""Recover refused historical ATP TXT and WTA XLSX exports as PRIVATE research evidence.

Read-only source ingestion: no CDB, provider/sports APIs, identity matching,
pricing as-of inference, scheduled jobs, or model activation. Retain ALL raw
rows, including bad CSV width / invalid scores; a display name is NOT an ID.
"""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import io
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

FIELDS_ATP=("Tournament","Date","Series","Court","Surface","Round","Best of",
    "Player_1","Player_2","Winner","Rank_1","Rank_2","Pts_1","Pts_2",
    "Odd_1","Odd_2","Score")
FIELDS_WTA=tuple(k for k in FIELDS_ATP if k!="Series")
SCORE=re.compile(r"(\d{1,2})-(\d{1,2})(?:\(\d{1,2}\))?")
NS="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL="{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKGREL="{http://schemas.openxmlformats.org/package/2006/relationships}"
MAX_BYTES=32_000_000
MAX_ROWS=200_000
SOURCES={
 "atp":("atp_tennis2.txt","1WWeNWFQO9JU_LehaKxau8li2tNlCoZMJ",17),
 "wta":("WTA Tennis 2007 - 2026 Daily update.xlsx","1qsqj8SyToK7yOd1szszx3CxPqdeJeSlE",16),
}

def _sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as fp:
        for x in iter(lambda: fp.read(1024*1024), b""):
            h.update(x)
    return h.hexdigest()

def _csv_records(path):
    with path.open("r",newline="",encoding="utf-8-sig") as f:
        lines=csv.reader(f)
        header=next(lines,None)
        if header != list(FIELDS_ATP):
            raise ValueError("Unexpected ATP legacy TXT header; refusing assumptions")
        for rownum,row in enumerate(lines,start=2):
            if rownum>MAX_ROWS: raise ValueError("Row limit exceeded")
            if row: yield rownum,row

def _xlsx_values(path):
    """Minimal stdlib XLSX reader: shared strings, inline strings, numbers.

    Do NOT infer Excel dates from unverified cell number formats; rejected
    archived workbook uses string-valued source dates, and those are retained.
    """
    with ZipFile(path) as z:
        names=set(z.namelist())
        if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
            raise ValueError("Incomplete XLSX workbook")
        if len(names)>150: raise ValueError("Unusually large XLSX archive member count")
        strings=[]
        if "xl/sharedStrings.xml" in names:
            for _,elem in ET.iterparse(z.open("xl/sharedStrings.xml"),events=("end",)):
                if elem.tag==NS+"si":
                    strings.append("".join(x.text or "" for x in elem.iter(NS+"t")))
                    elem.clear()
        wb=ET.fromstring(z.read("xl/workbook.xml"))
        sheets=wb.find(NS+"sheets")
        if sheets is None or len(sheets)!=1:
            raise ValueError("Unexpected XLSX sheets: independent sheet adapter required")
        rid=sheets[0].get(REL+"id")
        rels=ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target=next((x.get("Target") for x in rels if x.get("Id")==rid),None)
        if not target:
            raise ValueError("XLSX worksheet relationship missing")
        if target.startswith("/"):
            sheet=target.lstrip("/")
        else:
            from posixpath import normpath
            sheet=normpath("xl/"+target)
        if sheet not in names:
            raise ValueError("XLSX worksheet bytes missing")
        with z.open(sheet) as stream:
            for _,elem in ET.iterparse(stream,events=("end",)):
                if elem.tag != NS+"row":continue
                row=[]
                for cell in elem.findall(NS+"c"):
                    typ=cell.get("t")
                    raw=cell.find(NS+"v")
                    if typ=="inlineStr":
                        val="".join(t.text or "" for t in cell.iter(NS+"t"))
                    elif typ=="s" and raw is not None and raw.text is not None:
                        idx=int(raw.text)
                        if idx<0 or idx>=len(strings): raise ValueError("XLSX shared string index")
                        val=strings[idx]
                    elif typ=="b" and raw is not None:
                        val=raw.text or ""
                    else:
                        val=raw.text if raw is not None and raw.text is not None else ""
                    # Honor sparse cell addresses rather than losing blank columns.
                    ref=cell.get("r") or ""
                    m=re.match(r"([A-Z]+)",ref)
                    idx=0
                    for ch in (m.group(1) if m else ""):
                        idx=idx*26+ord(ch)-64
                    if idx and idx<=128:
                        while len(row)<idx-1:row.append("")
                    row.append(val)
                yield int(elem.get("r") or 0),row
                elem.clear()

def _wta_records(path):
    first=True
    for number,cells in _xlsx_values(path):
        if not cells:continue
        # Some owned workbooks have one CSV line per spreadsheet cell,
        # rather than a 16-column worksheet. Preserve this as source type.
        if len(cells)==1:
            raw=cells[0]
            parsed=next(csv.reader([raw]),[])
        elif len(cells)==2 and re.fullmatch(r"\d+",cells[0]) and "," in cells[1]:
            parsed=next(csv.reader([cells[1]]),[])
        else:
            parsed=cells
        if first:
            first=False
            if parsed != list(FIELDS_WTA):
                raise ValueError("Unexpected WTA XLSX original header")
            continue
        if number>MAX_ROWS: raise ValueError("Row limit exceeded")
        yield number,parsed

def _valid_score(score, winner_side, best_of):
    text=str(score).strip()
    if not text or re.search(r"\b(?:RET|DEF|W/O|WO|ABD|CANCEL|SUSP)\b",text,re.I):
        return False
    matches=list(SCORE.finditer(text))
    if not (2<=len(matches)<=5):return False
    residual=SCORE.sub("",text)
    if residual.strip(): return False
    a=b=0
    for m in matches:
        x,y=int(m.group(1)),int(m.group(2))
        if x==y or x>70 or y>70: return False
        hi,lo=max(x,y),min(x,y)
        if hi<6 or (hi==7 and lo not in (5,6)) or (hi>7 and hi-lo!=2):
            return False
        a+=int(x>y);b+=int(y>x)
    target=2 if best_of==3 else 3 if best_of==5 else 0
    return bool(target and max(a,b)==target and ((a>b)==(winner_side==1)))

def _year(date):
    try:
        return datetime.strptime(str(date),"%Y-%m-%d").year
    except (TypeError,ValueError):return None

def _positive_number(raw, *, odds=False):
    try:
        n=float(raw)
        if n<= (1 if odds else 0) or not (n < float("inf")):return None
        return n
    except (TypeError,ValueError):return None

def _record(tour, filename, source_sha, source_id, rownum, columns):
    fields=FIELDS_ATP if tour=="atp" else FIELDS_WTA
    shape_ok=len(columns)==len(fields)
    row=dict(zip(fields,columns)) if shape_ok else {}
    p1,p2=row.get("Player_1","").strip(),row.get("Player_2","").strip()
    winner=row.get("Winner","").strip()
    side=1 if winner==p1 and p1 and p2 and p1!=p2 else 2 if winner==p2 and p1 and p2 and p1!=p2 else None
    date=_year(row.get("Date")) if shape_ok else None
    try: bo=int(row.get("Best of","")) if shape_ok else None
    except (TypeError,ValueError):bo=None
    complete=bool(shape_ok and date and side and _valid_score(row.get("Score"),side,bo))
    if not shape_ok:
        status="QUARANTINE_CSV_COLUMN_SHAPE"
    elif date is None or not p1 or not p2 or side is None:
        status="QUARANTINE_INCOMPLETE_SOURCE_NAMES_OR_DATE"
    elif not complete:
        status="QUARANTINE_SCORE_OR_FINISH_NOT_PROVEN"
    else: status="RESEARCH_ONLY_NO_INDEPENDENT_EVENT_PLAYER_IDS"
    raw_json=json.dumps(columns,ensure_ascii=False,separators=(",",":"))
    return {
        "schema":1,"source_tour":tour,"source_type":"historical_results_ranks_odds",
        "source_filename":filename,"source_drive_file_id":source_id,
        "source_sha256":source_sha,"source_row_number":rownum,
        "source_original_row_sha256":hashlib.sha256(raw_json.encode()).hexdigest(),
        "source_values_raw":columns,
        "source_record":row if shape_ok else None,
        "source_year":date,"winner_source_side":side,"score_completed_verified":complete,
        "source_rank1_observed":_positive_number(row.get("Rank_1")),
        "source_rank2_observed":_positive_number(row.get("Rank_2")),
        "source_odd1_observed":_positive_number(row.get("Odd_1"),odds=True),
        "source_odd2_observed":_positive_number(row.get("Odd_2"),odds=True),
        "quote_observed_at":None,"rank_asof_verified":False,
        "original_event_id":None,"original_player1_id":None,"original_player2_id":None,
        "canonical_match_id":None,"import_ready":False,
        "canonical_write_authorized":False,"model_use_authorized":False,
        "status":status
    }

def build(root:Path,out:Path):
    checked={}
    for tour,(filename,file_id,_) in SOURCES.items():
        p=root/filename
        if not p.is_file() or p.is_symlink() or p.stat().st_size>MAX_BYTES:
            raise ValueError("Missing/unsafe/mis-sized original: "+filename)
        checked[tour]=(p,_sha(p),file_id)
    out.mkdir(parents=True,exist_ok=True)
    counts=Counter();by_tour={};years={}
    output=out/"rejected-source-observations.jsonl.gz"
    with output.open("wb") as f:
        with gzip.GzipFile(fileobj=f,filename="",mode="wb",mtime=0) as gz:
            with io.TextIOWrapper(gz,encoding="utf-8",newline="\n") as writer:
                for tour,(path,digest,file_id) in checked.items():
                    local=Counter();ys=Counter()
                    src=_csv_records(path) if tour=="atp" else _wta_records(path)
                    for rownum,columns in src:
                        item=_record(tour,path.name,digest,file_id,rownum,columns)
                        local[item["status"]]+=1
                        counts[item["status"]]+=1
                        if item["source_year"] is not None:ys[str(item["source_year"])]+=1
                        writer.write(json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n")
                    by_tour[tour]={"rows":sum(local.values()),"statuses":dict(sorted(local.items())),
                                   "sha256":digest,"file_id":file_id}
                    years[tour]=dict(sorted(ys.items()))
    report={"schema":1,"status":"REJECTED_DRIVE_SOURCE_ROWS_RETAINED_PRIVATE_NO_CDB_WRITE",
        "source_rows":sum(c["rows"] for c in by_tour.values()),"by_tour":by_tour,
        "years":years,"status_counts":dict(sorted(counts.items())),
        "observations_sha256":_sha(output),"source_api_requests":0,
        "sports_api_requests":0,"canonical_matches_proven":0,"canonical_cells_written":0,
        "accepted_source_matches_eligible_for_cdb":0,
        "reason":"Both original Drive sources lack independently verified event IDs and both player IDs; abbreviated names cannot be linked to canonical CDB by assumption",
        "status_policy":"Keep all rows including shape/score anomalies, preserve original bytes and provenance; make no ranking PIT or odds quote-time claim"}
    (out/"report.json").write_text(json.dumps(report,sort_keys=True,indent=2,ensure_ascii=False)+"\n")
    with (out/"SHA256SUMS").open("w") as f:
        for p in (out/"report.json",output):
            f.write(f"{_sha(p)}  {p.name}\n")
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    report=build(a.source_root,a.out)
    print(json.dumps({"status":report["status"],"source_rows":report["source_rows"],
        "status_counts":report["status_counts"],"canonical_cells_written":0,
        "sports_api_requests":0},sort_keys=True))
if __name__=="__main__":main()
