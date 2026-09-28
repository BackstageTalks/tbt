#!/usr/bin/env python3
"""Read-only audit of exact provider opening/current odds preserved in tbt-pro outputs."""
from __future__ import annotations
import argparse,gzip,json,re,sys,unicodedata
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"api"))
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities

def norm(v:Any)->str:
    s=unicodedata.normalize("NFKD",str(v or "").strip().lower())
    s="".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+"," ",s).split())

def event_id(match:Any)->str|None:
    p=match.provider_payload if isinstance(match.provider_payload,dict) else {}
    ident=p.get("_tbt_event_identity")
    vals=[ident.get("event_id") if isinstance(ident,dict) else None,p.get("_tbt_provider_event_id"),p.get("provider_event_id"),p.get("event_id"),p.get("eventId"),p.get("id")]
    e=p.get("event")
    if isinstance(e,dict): vals.append(e.get("id"))
    for v in vals:
        if v not in (None,""): return str(v)
    return None

def orient(match:Any,a:Any,b:Any)->str|None:
    a,b=norm(a),norm(b); m1,m2=norm(match.player1_name),norm(match.player2_name)
    if a==m1 and b==m2:return "direct"
    if a==m2 and b==m1:return "swapped"
    return None

def num(v:Any):
    try:return float(v) if v not in (None,"") else None
    except:return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--history-dir",default=".cache/tbt/history")
    ap.add_argument("--legacy-dir",default=".cache/tbt-pro")
    ap.add_argument("--out-dir",default=".cache/tbt/exact-market-audit")
    args=ap.parse_args()
    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)

    raw=load_partitions(Path(args.history_dir))
    matches,safety=sanitize_history_identities(raw)
    by_event={}
    for m in matches:
        eid=event_id(m)
        if eid: by_event[eid]=m

    files=sorted((Path(args.legacy_dir)/"outputs"/"2026"/"all").glob("*.json"))
    counts=Counter()
    best={}
    parse_errors=0
    for path in files:
        m=re.search(r"(\d{4}-\d{2}-\d{2})",path.name)
        snapshot_day=m.group(1) if m else ""
        try: rows=json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            parse_errors+=1; continue
        if not isinstance(rows,list): continue
        counts["raw_rows"]+=len(rows)
        for row in rows:
            if not isinstance(row,dict): continue
            eid=str(row.get("event_id") or row.get("match_id") or "")
            if not eid: continue
            quality=str(row.get("marq_data_status") or row.get("marq_source_quality") or "")
            if quality=="EXACT_BETTING_ODDS_WITH_OPENING": counts["exact_opening_rows"]+=1
            elif quality=="EXACT_CURRENT_ODDS_ONLY": counts["current_only_rows"]+=1
            else: continue
            if row.get("marq_exact_event_id_used") is not True:
                counts["non_exact_event_identity_excluded"]+=1; continue
            if str(row.get("status_type") or "").lower() not in {"notstarted","not_started","upcoming"}:
                counts["non_prematch_status_excluded"]+=1; continue
            quotes=row.get("market_quotes") if isinstance(row.get("market_quotes"),list) else []
            quote=None
            for q in quotes:
                if not isinstance(q,dict): continue
                if str(q.get("market_name") or "").lower() in {"full time","match winner"} or str(q.get("market_period") or "").lower()=="match":
                    quote=q; break
            if quote is None and quotes: quote=quotes[0] if isinstance(quotes[0],dict) else None
            if not quote: counts["no_quote"]+=1; continue
            o1,o2=num(quote.get("opening_1") if quote.get("opening_1") is not None else quote.get("initial_1")),num(quote.get("opening_2") if quote.get("opening_2") is not None else quote.get("initial_2"))
            c1,c2=num(quote.get("odds_1")),num(quote.get("odds_2"))
            has_open=all(v is not None and v>1 for v in (o1,o2))
            has_current=all(v is not None and v>1 for v in (c1,c2))
            if has_open: counts["rows_with_true_provider_opening"]+=1
            if has_current: counts["rows_with_current"]+=1
            if not has_current: continue
            candidate={
                "schema":1,"event_id":eid,"snapshot_day":snapshot_day,
                "player1":row.get("home_name") or row.get("player1"),
                "player2":row.get("away_name") or row.get("player2"),
                "match_start":row.get("match_start") or row.get("start_time"),
                "quality":quality,"opening_1":o1,"opening_2":o2,"current_1":c1,"current_2":c2,
                "provider_id":quote.get("provider_id"),"provider_name":quote.get("provider_name"),
                "source_id":quote.get("source_id"),"movement_status":quote.get("marq_v2_movement_status") or row.get("marq_movement_status"),
                "overround":quote.get("marq_v2_overround") or row.get("marq_overround"),
            }
            prev=best.get(eid)
            if prev is None or snapshot_day>str(prev.get("snapshot_day") or ""):
                best[eid]=candidate

    staged=[]
    for eid,row in best.items():
        counts["unique_exact_event_records"]+=1
        m=by_event.get(eid)
        if not m:
            counts["unmatched_canonical_event"]+=1; continue
        o=orient(m,row["player1"],row["player2"])
        if not o:
            counts["orientation_unverified"]+=1; continue
        counts["canonical_orientation_verified"]+=1
        def pair(a,b): return (a,b) if o=="direct" else (b,a)
        op1,op2=pair(row["opening_1"],row["opening_2"])
        cp1,cp2=pair(row["current_1"],row["current_2"])
        if op1 and op2: counts["canonical_with_true_opening"]+=1
        if op1 and cp1 and (abs(op1-cp1)>1e-12 or abs(op2-cp2)>1e-12): counts["canonical_with_provider_movement"]+=1
        staged.append({
            **row,"match_id":m.match_id,"orientation":o,
            "canonical_player1":m.player1_name,"canonical_player2":m.player2_name,
            "opening_p1":op1,"opening_p2":op2,"observed_current_p1":cp1,"observed_current_p2":cp2,
            "market_semantics":{
                "opening":"true provider opening preserved by getAllOddsForEvent when non-null",
                "observed_current":"provider current price at archived pre-match run; not automatically final closing price",
                "clv":"do not label as CLV unless a later closing observation is verified"
            }
        })

    with gzip.open(out/"exact_market_candidates.jsonl.gz","wt",encoding="utf-8") as fh:
        for r in staged: fh.write(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n")
    report={
        "schema":1,"generated_at_utc":datetime.now(timezone.utc).isoformat(),"zero_provider_api_requests":True,
        "canonical_rows":len(matches),"identity_safety":safety,
        "source_files":len(files),"parse_errors":parse_errors,"counts":dict(counts),
        "candidate_rows":len(staged),
        "policy":{
            "true_opening":"accepted only from exact-event provider market quote opening/initial fields",
            "observed_current":"pre-match archived provider current; not called closing",
            "future_merge":"combine true opening with latest verified pre-match observation before computing CLV-like metrics"
        }
    }
    (out/"exact_market_audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
