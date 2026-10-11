"""Fail-closed, read-only WTA 2026 Excel/CDB comparison. No write authorization."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

SOURCE_SHA="9bb1d5b2ecc57fc1c0866e50f722b2a4ebc7616090e8848b41b08f438ce7c753"
SOURCE_BLOB="aa88294e7d7edcc980302c07a1e9394e6efa5ea9"
NS="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REQUIRED={"WTA","Location","Tournament","Date","Surface","Round","Winner","Loser","WRank","LRank","Comment"}

def sha(path):
    h=sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""):h.update(b)
    return h.hexdigest()

def col_num(s):
    m=re.match(r"^[A-Z]+",s or "")
    if not m:raise ValueError("Missing worksheet column reference")
    x=0
    for c in m.group():x=x*26+ord(c)-64
    return x-1

def workbook_rows(path):
    if sha(path)!=SOURCE_SHA:raise ValueError("SOURCE_SHA256_DRIFT")
    with zipfile.ZipFile(path) as z:
        sheets=[p for p in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml",p)]
        if len(sheets)!=1:raise ValueError("Expected one worksheet")
        strings=[]
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(NS+"si"):
                strings.append("".join(x.text or "" for x in si.iter(NS+"t")))
        raw=[]
        for rn in ET.fromstring(z.read(sheets[0])).iter(NS+"row"):
            values={}
            for c in rn.findall(NS+"c"):
                n=col_num(c.get("r")); v=c.find(NS+"v"); kind=c.get("t","n")
                if kind=="inlineStr":
                    si=c.find(NS+"is"); value="".join(x.text or "" for x in si.iter(NS+"t")) if si is not None else None
                elif v is None:value=None
                elif kind=="s":value=strings[int(v.text)]
                elif kind in ("str","e","b"):value=v.text
                else:
                    try:value=float(v.text) if "." in v.text or "E" in v.text.upper() else int(v.text)
                    except (TypeError,ValueError):value=v.text
                values[n]=value
            if values:raw.append([values.get(i) for i in range(max(values)+1)])
    if not raw or len(raw[0])!=34 or not REQUIRED.issubset(raw[0]) or len(set(raw[0]))!=34:
        raise ValueError("Workbook header contract changed")
    header=raw[0];out=[]
    for i,values in enumerate(raw[1:],2):
        vals=values+[None]*(len(header)-len(values))
        row=dict(zip(header,vals));d=row.get("Date")
        if not isinstance(d,(int,float)) or not 46000<d<46400:
            raise ValueError("Invalid date at row "+str(i))
        row["_day"]=(datetime(1899,12,30)+timedelta(days=float(d))).date().isoformat()
        if row.get("Comment") not in ("Completed","Retired","Walkover"):
            raise ValueError("Invalid completion at row "+str(i))
        out.append(row)
    if len(out)!=2191:raise ValueError("Source count changed")
    return out

def norm(v):
    s=unicodedata.normalize("NFKD",str(v or ""))
    s="".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+"," ",s.casefold()).strip()

def parsed_name(name,abbreviated):
    tokens=norm(name).split()
    if len(tokens)<2:return None
    return (tokens[0],"".join(tokens[1:])) if abbreviated else (tokens[-1],"".join(tokens[:-1]))

def weak_name_match(raw,canon):
    a,b=parsed_name(raw,True),parsed_name(canon,False)
    return bool(a and b and a[0]==b[0] and b[1].startswith(a[1]))

def rank(v):
    try:
        n=float(v)
        return int(n) if 0<n<10000 and n.is_integer() else None
    except (TypeError,ValueError):return None

def empty(v):
    if v is None or isinstance(v,str) and v.strip().lower() in ("","nan","null","none"):
        return True
    try:
        import math
        return math.isnan(float(v))
    except (TypeError,ValueError,OverflowError):
        return False

def compare(source,current):
    counts=Counter();idx=defaultdict(list);seen=set()
    for c in current:
        if str(c.get("tour","")).casefold()!="wta":continue
        day=str(c.get("scheduled_at") or "")[:10]
        if not day.startswith("2026-"):continue
        mid=c.get("match_id")
        if not mid or mid in seen:raise ValueError("Duplicate or absent canonical match ID")
        seen.add(mid);idx[day].append(c)
    counts["canonical_wta2026_rows"]=len(seen)
    for r in source:
        counts["source_rows"]+=1
        counts["source_"+str(r["Comment"]).lower()]+=1
        if r["Comment"]!="Completed":
            counts["rejected_noncompleted"]+=1;continue
        candidates=[]
        for c in idx[r["_day"]]:
            a,b=c.get("player1_name"),c.get("player2_name")
            if weak_name_match(r["Winner"],a) and weak_name_match(r["Loser"],b) or weak_name_match(r["Winner"],b) and weak_name_match(r["Loser"],a):
                candidates.append(c)
        if not candidates:
            counts["no_name_day_diagnostic_match"]+=1;continue
        if len(candidates)!=1:
            counts["ambiguous_name_day"]+=1;continue
        c=candidates[0]
        if norm(r["Surface"])!=norm(c.get("surface")):
            counts["surface_mismatch"]+=1;continue
        p1=weak_name_match(r["Winner"],c.get("player1_name"))
        winner=c.get("player1_id") if p1 else c.get("player2_id")
        if str(c.get("winner_id"))!=str(winner):
            counts["winner_conflict"]+=1;continue
        counts["unique_name_day_surface_winner_DIAGNOSTIC_ONLY"]+=1
        for raw,field in (("WRank","player1_rank" if p1 else "player2_rank"),("LRank","player2_rank" if p1 else "player1_rank")):
            source_rank=rank(r.get(raw))
            if source_rank is None:counts["source_rank_invalid_or_empty"]+=1
            elif empty(c.get(field)):counts["RESEARCH_rank_null_NOT_WRITEABLE"]+=1
            elif rank(c.get(field))==source_rank:counts["rank_equal"]+=1
            else:counts["rank_conflict_or_different_snapshot"]+=1
        if norm(r.get("Tournament"))==norm(c.get("tournament")):counts["same_tournament_text"]+=1
        else:counts["different_tournament_text"]+=1
        if norm(r.get("Round"))==norm(c.get("round_name")):counts["same_round_text"]+=1
        else:counts["different_round_text"]+=1
    counts["approved_added_values"]=0
    counts["independently_attested_source_player_event_ID"]=0
    return dict(sorted(counts.items()))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--xlsx",required=True,type=Path)
    p.add_argument("--canonical",required=True,type=Path)
    p.add_argument("--report",required=True,type=Path)
    p.add_argument("--expected-cdb-sha",required=True)
    a=p.parse_args()
    if sha(a.canonical)!=a.expected_cdb_sha:raise ValueError("CANONICAL_SHA256_DRIFT")
    import pandas as pd
    cols=["match_id","tour","scheduled_at","player1_id","player2_id","winner_id",
          "player1_name","player2_name","surface","tournament","round_name","player1_rank","player2_rank"]
    rows=pd.read_parquet(a.canonical,columns=cols).to_dict("records")
    stats=compare(workbook_rows(a.xlsx),rows)
    report={"schema":1,"mode":"READ_ONLY","source_sha256":sha(a.xlsx),
        "canonical_year_2026_sha256":sha(a.canonical),"stats":stats,
        "approved_added_values":0,"canonical_written":False,"model_trained":False,
        "license_cleared":False,"stable_source_player_event_ids":False,
        "prematch_odds_quote_timestamps_proven":False,
        "warning":"Abbreviated names/day are research-only, never verified identity or write authorization."}
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("WTA2026_READ_ONLY_DIAGNOSTIC "+json.dumps(stats,sort_keys=True),flush=True)

if __name__=="__main__":main()
