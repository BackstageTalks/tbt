"""Validate pinned ATP weekly rankings against independent Sackmann match ranks."""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _positive_int(value):
    if value in (None, "", "-"):
        return None
    match = re.match(r"^(\d+)", str(value).replace(",", "").strip())
    return int(match.group(1)) if match else None


def _weeks(conn):
    rows=conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    out=[]
    for (name,) in rows:
        try:
            out.append(datetime.strptime(str(name), "%Y-%m-%d").date())
        except ValueError:
            pass
    return out


def _source_week(match_day, weeks):
    idx=bisect.bisect_right(weeks, match_day)-1
    if idx < 0:
        return None
    if weeks[idx] == match_day:
        idx -= 1
    return weeks[idx] if idx >= 0 else None


def _week_index(conn, week, cache):
    key=week.isoformat()
    if key in cache:
        return cache[key]
    rows=conn.execute(f'SELECT rank,name,points FROM "{key}"').fetchall()
    index={}
    dupes=set()
    for rank,name,points in rows:
        nk=_norm(name)
        item={"rank":_positive_int(rank),"points":_positive_int(points),"name":name}
        if not nk or item["rank"] is None:
            continue
        if nk in index:
            dupes.add(nk)
        else:
            index[nk]=item
    for nk in dupes:
        index.pop(nk,None)
    cache[key]=index
    return index


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sqlite-db", required=True)
    ap.add_argument("--csv", action="append", required=True)
    ap.add_argument("--out", required=True)
    args=ap.parse_args()

    conn=sqlite3.connect(args.sqlite_db)
    weeks=_weeks(conn)
    cache={}
    c=Counter()
    samples=[]
    for path_str in args.csv:
        path=Path(path_str)
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                c["match_rows"] += 1
                raw_date=str(row.get("tourney_date") or "").strip()
                try:
                    day=datetime.strptime(raw_date, "%Y%m%d").date()
                except ValueError:
                    c["invalid_date"] += 1
                    continue
                week=_source_week(day,weeks)
                if week is None:
                    c["before_source"] += 1
                    continue
                idx=_week_index(conn,week,cache)
                for side in ("winner","loser"):
                    expected=_positive_int(row.get(f"{side}_rank"))
                    name=str(row.get(f"{side}_name") or "").strip()
                    if expected is None or not name:
                        c["benchmark_rank_missing"] += 1
                        continue
                    c["benchmark_rank_values"] += 1
                    item=idx.get(_norm(name))
                    if item is None:
                        c["source_player_missing"] += 1
                        continue
                    c["source_player_linked"] += 1
                    diff=abs(int(expected)-int(item["rank"]))
                    if diff == 0:
                        c["rank_exact"] += 1
                    if diff <= 2:
                        c["rank_within2"] += 1
                    if diff <= 5:
                        c["rank_within5"] += 1
                    if diff > 5:
                        c["rank_difference_gt5"] += 1
                        if len(samples) < 100:
                            samples.append({
                                "date": day.isoformat(),
                                "source_week": week.isoformat(),
                                "player": name,
                                "benchmark_rank": expected,
                                "source_rank": item["rank"],
                                "difference": diff,
                            })
                    if item["points"] is not None:
                        c["source_points_available"] += 1
    conn.close()

    linked=c["source_player_linked"]
    benchmark=c["benchmark_rank_values"]
    report={
        "schema":1,
        "source":"Jupiterian/ATP-Rankings-API pinned SQLite",
        "source_weeks":len(weeks),
        "source_range":{"from":weeks[0].isoformat(),"to":weeks[-1].isoformat()},
        "counts":dict(c),
        "coverage_vs_benchmark": (linked/benchmark) if benchmark else 0.0,
        "exact_rate": (c["rank_exact"]/linked) if linked else 0.0,
        "within2_rate": (c["rank_within2"]/linked) if linked else 0.0,
        "within5_rate": (c["rank_within5"]/linked) if linked else 0.0,
        "points_rate_on_linked": (c["source_points_available"]/linked) if linked else 0.0,
        "point_in_time_policy":"latest weekly snapshot strictly before match date",
        "rapidapi_requests":0,
        "production_mutated":False,
        "large_difference_samples":samples,
    }
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    Path(args.out).write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
