#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,math,re,unicodedata
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from _bootstrap import ROOT
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities

def norm(v):
    s=unicodedata.normalize("NFKD",str(v or ""))
    s="".join(c for c in s if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+"," ",s).split())

def day(v):
    s=str(v or "").strip()
    for f in ("%Y-%m-%d","%m/%d/%Y"):
        try:return datetime.strptime(s,f).date()
        except ValueError:pass
    return None

def num(v):
    if v in (None,"","None","nan","NaN"): return None
    try:x=float(v)
    except (TypeError,ValueError): return None
    return x if math.isfinite(x) else None

def rate(n,d):
    n,d=num(n),num(d)
    if n is None or d is None or d<=0 or n<0 or n>d:return None
    x=n/d
    return x if 0<=x<=1 else None

def stats(row):
    out={}; svc={}
    for s in ("1","2"):
        a=num(row.get(f"Aces_{s}")); df=num(row.get(f"DoubleFaults_{s}"))
        sv=num(row.get(f"ServesTotal_{s}")); fi=num(row.get(f"Serve1st_{s}"))
        fw=num(row.get(f"Serve1stWon_{s}")); sw=num(row.get(f"Serve2ndWon_{s}"))
        if a is not None and a>=0 and a.is_integer():out[f"p{s}_aces"]=a
        if df is not None and df>=0 and df.is_integer():out[f"p{s}_double_faults"]=df
        vals={
            "first_serve_win":rate(fw,fi),
            "second_serve_win":rate(sw,None if sv is None or fi is None else sv-fi),
            "service_points_won":rate(None if fw is None or sw is None else fw+sw,sv),
            "break_point_return_win":rate(row.get(f"BreakPointsConverted_{s}"),row.get(f"BreakPointsTotal_{s}")),
        }
        for k,v in vals.items():
            if v is not None:out[f"p{s}_{k}"]=v
        if vals["service_points_won"] is not None:svc[s]=vals["service_points_won"]
    if "2" in svc:out["p1_return_points_won"]=1-svc["2"]
    if "1" in svc:out["p2_return_points_won"]=1-svc["1"]
    if "p2_break_point_return_win" in out:out["p1_break_point_serve_win"]=1-out["p2_break_point_return_win"]
    if "p1_break_point_return_win" in out:out["p2_break_point_serve_win"]=1-out["p1_break_point_return_win"]
    return out

def rows(path,tour):
    with Path(path).open("r",encoding="utf-8-sig",newline="") as h:
        for n,r in enumerate(csv.DictReader(h),2):
            d=day(r.get("GameD")); p1=str(r.get("Name_1") or "").strip(); p2=str(r.get("Name_2") or "").strip(); g=num(r.get("GRes_CUR_1"))
            if d is None or not p1 or not p2 or norm(p1)==norm(p2) or g not in (0.0,1.0):continue
            yield {"tour":tour,"day":d,"p1":p1,"p2":p2,"winner":p1 if g==1 else p2,"rank":str(r.get("TourRank") or "").strip(),"stats":stats(r)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--history-dir",required=True); ap.add_argument("--atp-csv",required=True); ap.add_argument("--wta-csv",required=True); ap.add_argument("--out",required=True); a=ap.parse_args()
    matches,safety=sanitize_history_identities(load_partitions(a.history_dir))
    if safety.get("quarantined_rows"):raise SystemExit("Canonical identity quarantine non-empty")
    exact=defaultdict(list); names=defaultdict(set)
    for m in matches:
        t=str(m.tour or "").lower(); d=m.scheduled_at.astimezone(timezone.utc).date(); pair=tuple(sorted((norm(m.player1_name),norm(m.player2_name))))
        exact[(t,d,pair)].append(m)
        names[(t,norm(m.player1_name))].add(str(m.player1_id)); names[(t,norm(m.player2_name))].add(str(m.player2_id))
    report={"schema":1,"canonical_rows":len(matches),"sources":{}}
    for tour,path in (("atp",a.atp_csv),("wta",a.wta_csv)):
        c=Counter(); by=defaultdict(Counter); seen=set()
        for r in rows(path,tour):
            c["usable_rows"]+=1; rank=r["rank"] or "missing"; by[rank]["rows"]+=1
            key=(tour,r["day"],tuple(sorted((norm(r["p1"]),norm(r["p2"])))))
            if key in seen:c["source_pair_date_duplicates"]+=1
            seen.add(key)
            if r["stats"]:c["rows_with_supported_stats"]+=1;by[rank]["rows_with_supported_stats"]+=1
            q=all(r["stats"].get(f"p{s}_service_points_won") is not None and r["stats"].get(f"p{s}_return_points_won") is not None for s in ("1","2"))
            if q:c["rows_quality_ready_both"]+=1;by[rank]["rows_quality_ready_both"]+=1
            cand=exact.get(key,[])
            if len(cand)==1:c["canonical_exact_unique"]+=1;by[rank]["canonical_exact_unique"]+=1
            elif len(cand)>1:c["canonical_exact_ambiguous"]+=1;by[rank]["canonical_exact_ambiguous"]+=1
            else:
                c["not_in_canonical_exact"]+=1;by[rank]["not_in_canonical_exact"]+=1
                st=[len(names.get((tour,norm(r["p1"])),set())),len(names.get((tour,norm(r["p2"])),set()))]
                if st==[1,1]:b="new_both_players_unique_canonical_name"
                elif all(x<=1 for x in st) and any(x==0 for x in st):b="new_no_name_ambiguity_some_new_players"
                else:b="new_name_identity_ambiguous"
                c[b]+=1;by[rank][b]+=1
        report["sources"][tour]={"file":Path(path).name,"counts":dict(c),"by_tour_rank":{k:dict(v) for k,v in sorted(by.items())}}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8");print(json.dumps(report,indent=2,ensure_ascii=False))
if __name__=="__main__":main()
