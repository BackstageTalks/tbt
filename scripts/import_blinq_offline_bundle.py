"""Import the processed BlinQ offline bundle without provider/API calls.

Fail-closed rules:
- canonical identity quarantine must be empty;
- existing matches are linked only by exact normalized player pair plus
  tournament/winner/round evidence in a bounded tournament window;
- conflicting existing statistics are never overwritten;
- Match Charting rows require a unique tour/date/player-pair match;
- only missing source matches are added, with deterministic source-scoped IDs
  unless a source player ID has been proven against canonical history.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions, write_year_partition
from tbt.data.offline_odds import norm_text, tournament_score
from tbt.schemas import MatchRecord

ROUND_ALIASES = {
    "f":"f","final":"f","sf":"sf","semifinal":"sf","qf":"qf","quarterfinal":"qf",
    "r16":"r16","round of 16":"r16","r32":"r32","round of 32":"r32",
    "r64":"r64","round of 64":"r64","r128":"r128","round of 128":"r128",
    "q1":"q1","q2":"q2","q3":"q3","q4":"q4","rr":"rr","round robin":"rr",
    "1st round qualifying":"q1","2nd round qualifying":"q2","3rd round qualifying":"q3",
}

def _ascii(v):
    return "".join(c for c in unicodedata.normalize("NFKD", str(v or "")) if not unicodedata.combining(c))

def _name(v):
    raw = _ascii(v)
    if "," in raw:
        a,b = raw.split(",",1)
        raw = f"{b} {a}"
    return " ".join(re.sub(r"[^a-z0-9]+"," ",raw.lower()).split())

def _round(v):
    t = norm_text(v)
    return ROUND_ALIASES.get(t,t)

def _surface(v):
    t=norm_text(v)
    for k in ("hard","clay","grass","carpet"):
        if k in t: return k
    return t or "unknown"

def _date(v):
    s=str(v or "").strip()
    for fmt in ("%Y%m%d","%Y-%m-%d","%Y/%m/%d"):
        try: return datetime.strptime(s,fmt).replace(hour=12,tzinfo=timezone.utc)
        except ValueError: pass
    return None

def _num(v):
    try: x=float(v)
    except (TypeError,ValueError): return None
    return x if math.isfinite(x) else None

def _int(v):
    x=_num(v)
    if x is None or x <= 0 or not float(x).is_integer(): return None
    return int(x)

def _rate(n,d):
    n,d=_num(n),_num(d)
    if n is None or d is None or d <= 0 or n < 0 or n > d: return None
    x=n/d
    return x if 0 <= x <= 1 else None

def _stats(row):
    out={}
    for side,src in (("p1","w"),("p2","l")):
        ace=_num(row.get(f"{src}_ace")); df=_num(row.get(f"{src}_df"))
        svpt=_num(row.get(f"{src}_svpt")); fi=_num(row.get(f"{src}_1stIn"))
        fw=_num(row.get(f"{src}_1stWon")); sw=_num(row.get(f"{src}_2ndWon"))
        if ace is not None and ace >= 0 and ace.is_integer(): out[f"{side}_aces"]=ace
        if df is not None and df >= 0 and df.is_integer(): out[f"{side}_double_faults"]=df
        a=_rate(fw,fi)
        b=_rate(sw, None if svpt is None or fi is None else svpt-fi)
        c=_rate(None if fw is None or sw is None else fw+sw, svpt)
        for field,val in (("first_serve_win",a),("second_serve_win",b),("service_points_won",c)):
            if val is not None: out[f"{side}_{field}"]=val
    if out.get("p2_service_points_won") is not None:
        out["p1_return_points_won"]=1.0-out["p2_service_points_won"]
    if out.get("p1_service_points_won") is not None:
        out["p2_return_points_won"]=1.0-out["p1_service_points_won"]
    return out

def _winner_name(m):
    if str(m.winner_id or "") == str(m.player1_id): return _name(m.player1_name)
    if str(m.winner_id or "") == str(m.player2_id): return _name(m.player2_name)
    return ""

def _pair(a,b):
    return tuple(sorted((_name(a),_name(b))))

def _source_key(row):
    return "|".join([
        "atp",str(row.get("source_type") or ""),str(row.get("tourney_id") or ""),
        str(row.get("match_num") or ""),_round(row.get("round")),
        "|".join(_pair(row.get("winner_name"),row.get("loser_name")))
    ])

def _level(row):
    st=str(row.get("source_type") or "").strip().lower()
    raw=str(row.get("tourney_level") or "").strip().upper()
    if st=="futures": return "itf futures"
    if raw=="G": return "grand slam"
    if raw=="M": return "masters 1000"
    if raw in {"250","500"}: return f"atp {raw}"
    if raw=="A": return "atp tour"
    return raw.lower() or "unknown"

def _candidate(source, match):
    delta=(match.scheduled_at.date()-source["date"].date()).days
    if delta < 0 or delta > 21: return None
    if _pair(match.player1_name,match.player2_name) != source["pair"]: return None
    if _winner_name(match) != _name(source["winner"]): return None
    ts,tev=tournament_score(source["tournament"],match.tournament)
    if ts <= 0: return None
    sr,cr=_round(source["round"]),_round(match.round_name)
    if sr and cr and sr != cr: return None
    score=4+ts+(2 if sr and cr and sr==cr else 0)+(2 if delta<=14 else 0)
    return score,tev,delta

def _merge_stats(match,incoming,counts,quarantine,source):
    existing=dict(match.stats or {})
    conflicts=[]
    for k,v in incoming.items():
        if v is None: continue
        old=existing.get(k)
        if old is not None and abs(float(old)-float(v)) > 1e-6:
            conflicts.append(k)
    if conflicts:
        counts["stat_conflict_matches"] += 1
        quarantine.append({"match_id":str(match.match_id),"source":source,"keys":conflicts})
        return False
    changed=False
    for k,v in incoming.items():
        if v is not None and existing.get(k) is None:
            existing[k]=float(v); changed=True; counts["stat_values_added"] += 1
    if changed:
        match.stats=existing
    return changed

def import_futures(path,matches,counts,quarantine,*,existing_only=False):
    rows=[]; seen=set()
    with Path(path).open("r",encoding="utf-8-sig",newline="") as h:
        for n,row in enumerate(csv.DictReader(h),start=2):
            counts["foundation_source_rows"] += 1
            d=_date(row.get("tourney_date"))
            w=str(row.get("winner_name") or "").strip()
            l=str(row.get("loser_name") or "").strip()
            if not d or not w or not l or _name(w)==_name(l):
                counts["foundation_invalid_rows"] += 1; continue
            key=_source_key(row)
            if key in seen:
                counts["foundation_source_duplicates"] += 1; continue
            seen.add(key)
            rows.append({
                "row":row,"line":n,"date":d,"winner":w,"loser":l,"pair":_pair(w,l),
                "tournament":str(row.get("tourney_name") or ""),
                "round":str(row.get("round") or ""),"key":key,
                "wid":str(row.get("winner_id") or "").strip(),
                "lid":str(row.get("loser_id") or "").strip(),
            })

    by_pair=defaultdict(list)
    for m in matches:
        if str(m.tour or "").lower()=="atp":
            by_pair[_pair(m.player1_name,m.player2_name)].append(m)

    votes=defaultdict(set); links={}
    for src in rows:
        cands=[]
        for m in by_pair.get(src["pair"],[]):
            c=_candidate(src,m)
            if c: cands.append((c[0],m,c))
        if not cands: continue
        cands.sort(key=lambda x:x[0],reverse=True)
        top=[x for x in cands if x[0]==cands[0][0]]
        if len(top)!=1:
            counts["foundation_ambiguous_existing"] += 1; continue
        _,m,e=top[0]
        links[src["key"]]=m
        p1n,p2n=_name(m.player1_name),_name(m.player2_name)
        if _name(src["winner"])==p1n and _name(src["loser"])==p2n:
            wi,li=str(m.player1_id),str(m.player2_id)
        elif _name(src["winner"])==p2n and _name(src["loser"])==p1n:
            wi,li=str(m.player2_id),str(m.player1_id)
        else:
            continue
        if src["wid"]: votes[("atp",src["wid"])].add(wi)
        if src["lid"]: votes[("atp",src["lid"])].add(li)

    mapping={k:next(iter(v)) for k,v in votes.items() if len(v)==1}
    counts["foundation_players_proven"]=len(mapping)
    changed=set()
    existing_ids={str(m.match_id) for m in matches}

    for src in rows:
        r=src["row"]
        match=links.get(src["key"])
        incoming=_stats(r)
        if match is not None:
            counts["foundation_existing_identity"] += 1
            if _merge_stats(match,incoming,counts,quarantine,"futures_existing"):
                changed.add(match.scheduled_at.year)
                counts["foundation_existing_stats_updated"] += 1
            continue

        if existing_only:
            counts["foundation_unmatched_quarantined_for_identity_review"] += 1
            continue
        digest=hashlib.sha256(src["key"].encode()).hexdigest()[:24]
        mid=f"hist-js:atp:{digest}"
        if mid in existing_ids:
            counts["foundation_already_present_id"] += 1; continue
        def pid(source_id,name):
            if source_id and ("atp",source_id) in mapping: return mapping[("atp",source_id)]
            token=source_id or ("name:"+hashlib.sha256(_name(name).encode()).hexdigest()[:16])
            token=re.sub(r"[^A-Za-z0-9_.:-]+","_",token)
            return f"hist-js:atp:{token}"
        p1=pid(src["wid"],src["winner"]); p2=pid(src["lid"],src["loser"])
        if p1==p2:
            counts["foundation_player_collision"] += 1; continue
        rank1=_int(r.get("winner_rank")); rank2=_int(r.get("loser_rank"))
        item=MatchRecord(
            match_id=mid,tour="atp",scheduled_at=src["date"],
            player1_id=p1,player1_name=src["winner"],
            player2_id=p2,player2_name=src["loser"],
            surface=_surface(r.get("surface")),tournament=src["tournament"],
            tournament_id=str(r.get("tourney_id") or ""),tournament_level=_level(r),
            round_name=_round(src["round"]),player1_rank=rank1,player2_rank=rank2,
            winner_id=p1,status="completed",best_of=_int(r.get("best_of")),
            indoor=None,stats=incoming,
            provider_payload={
                "_tbt_provider_event_id":mid,
                "_tbt_source_category_name":f"historical_{str(r.get('source_type') or 'offline')}",
                "_tbt_event_identity":{"event_id":mid,"home":src["winner"],"away":src["loser"],"status":"completed"},
                "_tbt_offline_import":{"schema":1,"source":"blinq_processed_futures_qualifying","source_key":src["key"]},
            },
        )
        matches.append(item); by_pair[src["pair"]].append(item); existing_ids.add(mid)
        changed.add(src["date"].year); counts["foundation_new_matches"] += 1
    return changed

def _chart_date(row):
    d=_date(row.get("date"))
    if d: return d
    mid=str(row.get("match_id") or "")
    m=re.match(r"(\d{8})",mid)
    return _date(m.group(1)) if m else None

def _chart_stats(row):
    out={}
    def put(field,key,count=False):
        v=_num(row.get(key))
        if v is None: return
        if count:
            if v>=0 and v.is_integer(): out[field]=v
        elif 0<=v<=1: out[field]=v
    put("aces","ov_aces",True); put("double_faults","ov_dfs",True)
    put("first_serve_win","first_win_pct"); put("second_serve_win","second_win_pct")
    put("service_points_won","service_points_won_pct"); put("return_points_won","return_points_won_pct")
    put("first_strike_serve_win","servebasics_total_short_win_pct")
    ret=_rate(row.get("returnoutcomes_total_in_play"),row.get("returnoutcomes_total_returnable"))
    if ret is not None: out["return_in_play_rate"]=ret
    put("return_deep_rate","returndepth_total_deep_pct")
    put("break_point_serve_win","keypointsserve_bp_win_pct")
    put("break_point_return_win","keypointsreturn_bpo_win_pct")
    put("net_points_win","netpoints_netpoints_net_win_pct")
    end=sum(x or 0 for x in (_num(row.get("shottypes_f_pt_ending")),_num(row.get("shottypes_b_pt_ending")),_num(row.get("shottypes_net_pt_ending"))))
    win=sum(x or 0 for x in (_num(row.get("shottypes_f_winners")),_num(row.get("shottypes_b_winners")),_num(row.get("shottypes_net_winners"))))
    forced=sum(x or 0 for x in (_num(row.get("shottypes_f_induced_forced")),_num(row.get("shottypes_b_induced_forced")),_num(row.get("shottypes_net_induced_forced"))))
    unf=sum(x or 0 for x in (_num(row.get("shottypes_f_unforced")),_num(row.get("shottypes_b_unforced")),_num(row.get("shottypes_net_unforced"))))
    if end>0:
        attack=(win+forced)/end; ue=unf/end
        if 0<=attack<=1: out["attacking_points_rate"]=attack
        if 0<=ue<=1: out["unforced_error_rate"]=ue
    return out

def import_charting(paths,matches,counts,quarantine):
    index=defaultdict(list)
    for m in matches:
        index[(str(m.tour or "").lower(),m.scheduled_at.date(),_pair(m.player1_name,m.player2_name))].append(m)
    changed=set()
    for path in paths:
        with Path(path).open("r",encoding="utf-8-sig",newline="") as h:
            for n,row in enumerate(csv.DictReader(h),start=2):
                counts["charting_source_rows"] += 1
                tour=str(row.get("sex") or "").strip().lower()
                if tour not in {"atp","wta"}: continue
                d=_chart_date(row); player=str(row.get("player") or "").strip(); opp=str(row.get("opponent") or "").strip()
                if not d or not player or not opp: counts["charting_invalid_rows"] += 1; continue
                candidates=[]
                for delta in (-1,0,1):
                    candidates += index.get((tour,(d+timedelta(days=delta)).date(),_pair(player,opp)),[])
                unique={str(x.match_id):x for x in candidates}
                if len(unique)!=1:
                    counts["charting_unmatched_or_ambiguous"] += 1; continue
                match=next(iter(unique.values()))
                p1=_name(match.player1_name); pn=_name(player)
                prefix="p1" if pn==p1 else "p2" if pn==_name(match.player2_name) else ""
                if not prefix:
                    counts["charting_orientation_failed"] += 1; continue
                raw=_chart_stats(row)
                incoming={f"{prefix}_{k}":v for k,v in raw.items()}
                if _merge_stats(match,incoming,counts,quarantine,f"charting:{Path(path).name}:{n}"):
                    changed.add(match.scheduled_at.year); counts["charting_rows_updated"] += 1
    return changed

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--history-dir",required=True)
    ap.add_argument("--futures-csv",required=True)
    ap.add_argument("--charting-csv",action="append",default=[])
    ap.add_argument("--out-dir",required=True)
    ap.add_argument("--write-partitions",action="store_true")
    ap.add_argument("--existing-only",action="store_true",help="Never add unmatched source matches; enrich identity-proven canonical rows only.")
    args=ap.parse_args()
    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    matches,safety=sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history identity quarantine is non-empty")
    counts=Counter(); quarantine=[]
    changed=set()
    changed |= import_futures(args.futures_csv,matches,counts,quarantine,existing_only=args.existing_only)
    changed |= import_charting(args.charting_csv,matches,counts,quarantine)
    if args.write_partitions:
        for year in sorted(changed):
            write_year_partition(matches,Path(args.history_dir),year,extra_manifest={"coverage_status":"blinq_offline_bundle_imported"})
    report={
        "schema":1,"api_requests":0,"production_mutated":False,
        "counts":dict(counts),"changed_years":sorted(changed),
        "quarantine_rows":len(quarantine),
    }
    (out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    with (out/"quarantine.jsonl").open("w",encoding="utf-8") as h:
        for row in quarantine: h.write(json.dumps(row,ensure_ascii=False)+"\n")
    print(json.dumps(report,indent=2,ensure_ascii=False))

if __name__=="__main__":
    main()
