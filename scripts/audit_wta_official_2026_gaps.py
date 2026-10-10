"""Read-only WTA 2026 official ranking versus canonical CDB gap audit."""
from __future__ import annotations
import argparse, csv, gzip, hashlib, json, re, unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from _bootstrap import ROOT
from tbt.data.history_snapshot import load_snapshot

SHA = "4267e37ba6357eb11cfb0e9346c3c59eac8a17431e1f19deb5fffa9573a9bf03"
def norm(value):
    s = unicodedata.normalize("NFKD",str(value or "").casefold())
    return re.sub(r"[^a-z0-9]+"," ","".join(x for x in s if not unicodedata.combining(x))).strip()
def column(headers, *options):
    by={norm(h).replace(" ",""):h for h in headers}
    return next((by[norm(opt).replace(" ","")] for opt in options if norm(opt).replace(" ","") in by),None)
def day(value):
    s=str(value or "").strip()
    try:
        return datetime.strptime(s,"%Y%m%d").date() if re.fullmatch(r"\d{8}",s) else date.fromisoformat(s[:10])
    except ValueError: return None
def load(source):
    if hashlib.sha256(source.read_bytes()).hexdigest()!=SHA: raise ValueError("Source hash changed")
    counts=Counter(); by={}; conflicts=set()
    with gzip.open(source,"rt",encoding="utf-8-sig",newline="") as stream:
        reader=csv.DictReader(stream); h=reader.fieldnames or []
        d=column(h,"rankedAt","ranking_date","rankingDate","rank_date","date")
        p=column(h,"sackmann_id","sackmannId","sackmann_player_id","player_id")
        r=column(h,"rank","ranking","rank_position")
        n=column(h,"player_name","playerName","full_name","name")
        if not all((d,p,r)): raise ValueError("Source schema not yet verified: "+str(h))
        for row in reader:
            counts["source_rows"]+=1
            dt=day(row.get(d)); player=str(row.get(p) or "").strip(); value=str(row.get(r) or "").strip()
            if dt is None or not player or not value.isdigit() or int(value)<1:
                counts["invalid"]+=1; continue
            key=(dt,player)
            item=(int(value),norm(row.get(n)) if n else "",bool("sackmann" in p.lower()))
            if key in by and by[key]!=item: conflicts.add(key)
            else: by[key]=item
    if counts["source_rows"]!=16927: raise ValueError("Pinned source row count changed")
    for key in conflicts: by.pop(key,None)
    return by,dict(counts),{"headers":h,"date":d,"id":p,"rank":r,"name":n,"conflict_keys":len(conflicts)}

def load_crosswalk(path):
    """Only independently linked canonical->Sackmann ID mappings are eligible.

    Conflicting or multiply owned player IDs fail closed. This sidecar was
    derived from independently matched same-day source matches, not from the
    official ranking source or a name-only mapping.
    """
    rows_by_canonical={}
    ambiguous_canonical=set()
    counts=Counter()
    with gzip.open(path,"rt",encoding="utf-8") as handle:
        for line in handle:
            if not line.strip(): continue
            counts["profile_rows"]+=1
            row=json.loads(line)
            profile=row.get("profile") or {}
            canonical=str(row.get("player_id") or "").strip()
            sackmann=str(profile.get("sackmann_id") or "").strip()
            name=norm(row.get("canonical_name"))
            if row.get("schema")!=1 or not canonical or not sackmann.isdigit() or not name or int(row.get("evidence_match_count") or 0)<1:
                counts["excluded_without_strict_link"]+=1
                continue
            item={"sackmann_id":str(int(sackmann)),"name":name}
            if canonical in rows_by_canonical and rows_by_canonical[canonical]!=item:
                ambiguous_canonical.add(canonical)
            else:
                rows_by_canonical[canonical]=item
    for canonical in ambiguous_canonical:
        rows_by_canonical.pop(canonical,None)
    reverse=defaultdict(set)
    for canonical,item in rows_by_canonical.items():
        reverse[item["sackmann_id"]].add(canonical)
    duplicated={sid for sid,owners in reverse.items() if len(owners)!=1}
    verified={cid:item for cid,item in rows_by_canonical.items() if item["sackmann_id"] not in duplicated}
    counts["conflicting_canonical_ids"]=len(ambiguous_canonical)
    counts["multiply_owned_sackmann_ids"]=len(duplicated)
    counts["verified_crosswalk_players"]=len(verified)
    return verified,dict(counts)

def inspect(matches,source,crosswalk):
    rows=[]; counts=Counter(); dates=defaultdict(dict)
    for (when,pid),data in source.items(): dates[pid][when]=data
    for m in matches:
        if str(m.tour).lower()!="wta" or m.scheduled_at.year!=2026: continue
        current=m.scheduled_at.astimezone(timezone.utc).date()
        if not date(2026,6,16)<=current<=date(2026,9,29): continue
        counts["wta_window"]+=1
        if m.player1_rank is not None and m.player2_rank is not None:
            counts["both_present"]+=1; continue
        pairs=[]; invalid=False
        for pid,name in ((m.player1_id,m.player1_name),(m.player2_id,m.player2_name)):
            identity=crosswalk.get(str(pid))
            if identity is None or identity["name"]!=norm(name):
                counts["missing_independent_crosswalk"]+=1
                invalid=True; break
            choices=[(d,item) for d,item in dates.get(identity["sackmann_id"],{}).items()
                     if 0<(current-d).days<=8]
            if not choices: invalid=True; break
            d,(rank,source_name,verified_id)=max(choices)
            if source_name and source_name!=norm(name): invalid=True; break
            if not verified_id and not source_name: invalid=True; break
            pairs.append((d,rank))
        if invalid or len(pairs)!=2:
            counts["missing_identity_or_rank"]+=1; continue
        if pairs[0][0]!=pairs[1][0]:
            counts["rank_week_conflict"]+=1; continue
        values=[m.player1_rank,m.player2_rank]; expected=[pairs[0][1],pairs[1][1]]
        if any(v is not None and int(v)!=new for v,new in zip(values,expected)):
            counts["existing_conflict"]+=1; continue
        rows.append({"match_id":str(m.match_id),"scheduled_at":m.scheduled_at.isoformat(),
                     "ranking_as_of":pairs[0][0].isoformat(),"canonical":values,
                     "proposed":expected,"candidate_only":True})
        counts["candidate_matches"]+=1
        counts["missing_rank_values"]+=sum(v is None for v in values)
    if len(set(x["match_id"] for x in rows))!=len(rows): raise ValueError("Duplicate canonical ID")
    return rows,dict(counts)
def main():
    p=argparse.ArgumentParser()
    for flag in ("source","history_dir","out_dir"):p.add_argument("--"+flag.replace("_","-"),required=True,type=Path)
    p.add_argument("--crosswalk",required=True,type=Path)
    a=p.parse_args(); by,c,s=load(a.source)
    crosswalk,crosswalk_counts=load_crosswalk(a.crosswalk)
    matches=load_snapshot(a.history_dir/"history-2026.parquet")
    rows,counts=inspect(matches,by,crosswalk)
    a.out_dir.mkdir(parents=True,exist_ok=True)
    (a.out_dir/"candidates.jsonl").write_text("".join(json.dumps(x)+"\n" for x in rows))
    report={"schema":1,"status":"read_only","source":s,"source_counts":c,"crosswalk_counts":crosswalk_counts,"counts":counts,
            "stage_rows":len(rows),"canonical_year_rows":len(matches),"api_requests":0,
            "production_mutated":False,"model_promoted":False,"write_authorized":False}
    (a.out_dir/"report.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
if __name__=="__main__":main()
