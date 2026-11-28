"""Offline historical GAMES/SETS comparison from an issued ledger export."""
import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from tbt.services.point_sg import LEVELS, summary, grade


def report(ledger, confirmed_only=False):
    samples = defaultdict(list)
    days = []
    issued_counts = defaultdict(int)
    seen = set()
    unsettled = 0
    zone = ZoneInfo("Europe/Bratislava")
    for row in ledger:
        level = row.get("competition")
        if level not in LEVELS:
            continue
        for pick in row.get("market_publications", []):
            market = pick.get("market")
            if market not in ("games","sets") or pick.get("publication_status") != "published":
                continue
            if (pick.get("price_status") != "priced_projection" or not pick.get("odds")
                    or pick.get("odds_source") not in ("rapidapi","propline")
                    or (pick.get("odds_source") == "propline" and not pick.get("odds_bookmaker"))):
                continue
            snapshot = pick.get("issued_snapshot") or {}
            if confirmed_only and (snapshot.get("source") != "pre_deploy_feed_confirmed"
                                   or snapshot.get("odds") != pick["odds"]):
                continue
            start = datetime.fromisoformat(row.get("original_scheduled_at") or row["scheduled_at"])
            quoted = pick.get("captured_at")
            issued = snapshot.get("confirmed_at") or pick.get("issued_at")
            if not quoted or not issued or not datetime.fromisoformat(quoted) <= datetime.fromisoformat(issued) < start:
                continue
            identity = (row["event_id"], market, pick["selection_id"])
            if identity in seen:
                continue
            seen.add(identity)
            for group in ("Spolu", level):
                issued_counts[market,group] += 1
            day = start.astimezone(zone).date()
            days.append(day)
            result = pick.get("result") or {}
            if result.get("actual_count") is None or result.get("status") not in ("hit","miss","push","void"):
                unsettled += 1
                continue
            _, side, line = pick["selection_id"].split(":")
            if side not in ("over","under"):
                continue
            status, profit = grade({"side":side,"line":float(line),"odds":pick["odds"]}, result["actual_count"])
            if result["status"] == "void" and status != "push":
                unsettled += 1
                continue
            for group in ("Spolu",level):
                samples[market,group].append((day,status,profit))
    if not days:
        return {"issued":0,"rows":[]}
    length = (max(days)-min(days)).days + 1
    return {"first":str(min(days)), "last":str(max(days)), "days":length, "issued":len(seen),
            "ungraded":unsettled, "rows":[{"market":m,"level":g,"issued_per_day":issued_counts[m,g]/length,**summary(samples[m,g],length)}
                                         for m in ("games","sets") for g in ("Spolu",*LEVELS)]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args()
    data = json.loads(args.ledger.read_bytes())
    print(json.dumps({"published":report(data),"confirmed":report(data,True)}, indent=2))
