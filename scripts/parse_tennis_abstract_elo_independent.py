#!/usr/bin/env python3
"""Parse four independently dated Tennis Abstract boards for RESEARCH checks.

Unlike the archival same-week snapshot importer, validation must not assume
ATP/WTA/season yElo report pages refresh on the same date. Each per-board
date is independently retained. Never promote or retroactively backfill.
"""
from __future__ import annotations
import argparse
import json
from datetime import date
from pathlib import Path
from parse_tennis_abstract_elo import parse_elo, parse_yelo

def build(sources: dict[str,str], output_dir: Path) -> dict:
    output_dir.mkdir(parents=True,exist_ok=True)
    report={"schema":1,"source":"Tennis Abstract independently dated reports",
            "point_in_time_snapshots":True,"training_eligible":False,
            "training_ineligible_reason":"Contemporaneous reference only; no historical Elo backfill",
            "tables":{},"snapshot_dates":{}}
    for name,tour,parser in [
        ("atp_elo","atp",parse_elo),("wta_elo","wta",parse_elo),
        ("atp_yelo","atp",parse_yelo),("wta_yelo","wta",parse_yelo)]:
        if name not in sources:raise ValueError(f"Missing independent TA board {name}")
        df,snapshot=parser(sources[name],tour=tour)
        if len(df)<100:raise ValueError(f"Suspicious small TA board {name}: {len(df)}")
        if date.fromisoformat(snapshot)>date.today():
            raise ValueError("TA report source date is in the future")
        df.to_csv(output_dir/f"{name}.csv",index=False)
        report["tables"][name]={"rows":len(df),"snapshot_date":snapshot,
                                 "columns":list(df.columns)}
        report["snapshot_dates"][name]=snapshot
    report["all_boards_same_date"]=len(set(report["snapshot_dates"].values()))==1
    (output_dir/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    return report

def main():
    p=argparse.ArgumentParser()
    for name in ["atp_elo","wta_elo","atp_yelo","wta_yelo"]:
        p.add_argument("--"+name.replace("_","-")+"-html",required=True,type=Path)
    p.add_argument("--out-dir",required=True,type=Path)
    a=p.parse_args()
    raw={key:getattr(a,key+"_html").read_text(encoding="utf-8",errors="replace")
         for key in ("atp_elo","wta_elo","atp_yelo","wta_yelo")}
    result=build(raw,a.out_dir)
    print("TA_INDEPENDENT_DATES_VERIFIED",json.dumps(result["snapshot_dates"]))

if __name__=="__main__":main()
