#!/usr/bin/env python3
"""Explain source-native historical break-point linkage failures without changing CDB."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from audit_pbp_source_vs_current_cdb import FILES
from import_historical_match_foundation import _source_type, _stats
from recover_cdb_sackmann_breakpoints import _load, source_match_id
from tbt.data.offline_odds import norm_text


def reject_reasons(match, row, tour, kind, path):
    reasons=[]
    if str(match.tour).lower()!=tour:
        reasons.append("tour")
    if not match.is_completed or str(match.status).lower()!="completed":
        reasons.append("not_completed")
    if match.scheduled_at >= datetime.now(timezone.utc):
        reasons.append("future")
    raw=str(row.get("tourney_date") or "").strip()
    if not re.fullmatch(r"\\d{8}",raw):
        reasons.append("source_date_invalid")
    elif match.scheduled_at.strftime("%Y%m%d") != raw:
        reasons.append("date_differs")
    w,l=str(row.get("winner_id") or "").strip(),str(row.get("loser_id") or "").strip()
    if not w or not l or w==l or not re.fullmatch(r"[A-Za-z0-9_.:-]+",w+l):
        reasons.append("source_player_ids_invalid")
    if (str(match.player1_id)!=f"hist-js:{tour}:{w}" or
        str(match.player2_id)!=f"hist-js:{tour}:{l}" or
        str(match.winner_id)!=str(match.player1_id)):
        reasons.append("canonical_player_ids_or_winner")
    if (norm_text(match.player1_name)!=norm_text(row.get("winner_name")) or
        norm_text(match.player2_name)!=norm_text(row.get("loser_name"))):
        reasons.append("canonical_names")
    ctx=match.provider_payload
    if not isinstance(ctx,dict):
        reasons.append("context_not_object")
        return reasons
    ev=ctx.get("_tbt_statistics")
    if not isinstance(ev,dict) or ev.get("source")!="jeff_sackmann_match_snapshot:"+path.name:
        reasons.append("source_lineage")
    if ctx.get("_tbt_provider_event_id")!=str(match.match_id):
        reasons.append("provider_event_id")
    if ctx.get("_tbt_source_category_name")!="historical_"+kind:
        reasons.append("source_category")
    return reasons


def profile(history,source):
    matches=_load(history)
    index={str(x.match_id):x for x in matches if str(x.match_id).startswith("hist-js:")}
    counts=Counter()
    date_offsets=Counter()
    for path in sorted(source.rglob("*.csv")):
        rel=path.relative_to(source).as_posix()
        if not any(re.fullmatch(regex,rel) for regex in FILES):
            continue
        tour=rel.split("/",1)[0]
        with path.open(encoding="utf-8-sig",newline="") as fh:
            for no,row in enumerate(csv.DictReader(fh),2):
                mid,kind=source_match_id(tour,path,row,no)
                rec=index.get(mid)
                if rec is None:
                    continue
                counts["native_id_match"]+=1
                reasons=reject_reasons(rec,row,tour,kind,path)
                if not reasons:
                    counts["lineage_ok"]+=1
                else:
                    counts["lineage_failed"]+=1
                    counts["first_"+reasons[0]]+=1
                    for x in reasons:
                        counts["all_"+x]+=1
                    if reasons==["date_differs"]:
                        counts["solely_date_differs"]+=1
                        try:
                            diff=(rec.scheduled_at.date()-datetime.strptime(row["tourney_date"],"%Y%m%d").date()).days
                            date_offsets[str(diff)]+=1
                        except ValueError:
                            pass
                if rec.stats.get("p1_break_point_return_win") is None or rec.stats.get("p2_break_point_return_win") is None:
                    counts["matches_with_bp_return_null"]+=1
                    if not reasons:
                        counts["lineage_ok_with_bp_return_null"]+=1
                    elif reasons==["date_differs"]:
                        counts["sole_date_failed_with_bp_return_null"]+=1
    return {"counts":dict(sorted(counts.items())),"date_offsets":date_offsets.most_common(35),"writes":0}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--history-dir",type=Path,required=True)
    p.add_argument("--source-dir",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    report=profile(a.history_dir,a.source_dir)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("CDB_SACKMANN_NATIVE_LINEAGE_DIAGNOSTIC",json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()
