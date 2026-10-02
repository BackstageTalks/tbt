#!/usr/bin/env python3
from __future__ import annotations
import csv, json, time
from pathlib import Path
import requests

YEARS = range(2010, 2027)
METRIC = "first_serve_percent"
BASE = "https://api.wtatennis.com/tennis/stats/{year}/{metric}"
OUT = Path("artifacts/wta_stats_2010_2026.csv")
SUMMARY = Path("artifacts/wta_stats_2010_2026_summary.csv")
PREFERRED = [
    "season","PlayerNbr","First_Name","Last_Name","Nationality","Current_Rank","MatchCount",
    "Aces","Double_Faults","first_serve_percent","first_serve_won_percent",
    "second_serve_won_percent","service_points_won_percent","breakpoint_saved_percent",
    "service_games_won_percent","first_return_percent","second_return_percent",
    "return_games_won_percent","breakpoint_converted_percent","return_points_won_percent",
    "source_url"
]

def fetch_year(session, year):
    url = BASE.format(year=year, metric=METRIC)
    players = {}
    for page in range(100):
        response = session.get(url, params={"page": page, "pageSize": 100, "sort": "desc"}, timeout=30)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise RuntimeError(f"{year}: unexpected payload")
        if not data:
            break
        added = 0
        for row in data:
            pid = row.get("PlayerNbr")
            key = str(pid) if pid not in (None, "") else json.dumps(row, sort_keys=True, ensure_ascii=False)
            if key not in players:
                added += 1
            players[key] = row
        if added == 0 or len(data) < 100:
            break
        time.sleep(0.08)
    rows = list(players.values())
    for row in rows:
        row["season"] = year
        row["source_url"] = url
    return rows

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (BlinQ historical WTA stats export)",
        "Origin": "https://www.wtatennis.com",
        "Referer": "https://www.wtatennis.com/stats",
        "Accept": "application/json",
        "account": "wta",
    })
    all_rows = []
    summary = []
    for year in YEARS:
        rows = fetch_year(session, year)
        if not rows:
            raise RuntimeError(f"{year}: no rows returned")
        summary.append({"season": year, "rows": len(rows)})
        all_rows.extend(rows)
        print(f"{year}: {len(rows)} rows", flush=True)

    extras = sorted({key for row in all_rows for key in row} - set(PREFERRED))
    fields = PREFERRED + extras
    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(all_rows, key=lambda r: (
            int(r["season"]),
            int(r.get("Current_Rank") or 10**9),
            str(r.get("Last_Name") or ""),
            str(r.get("First_Name") or ""),
        )):
            writer.writerow(row)

    with SUMMARY.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["season", "rows"])
        writer.writeheader()
        writer.writerows(summary)

    identities = {(row["season"], str(row.get("PlayerNbr"))) for row in all_rows}
    if len(identities) != len(all_rows):
        raise RuntimeError("duplicate season/player rows detected")
    print(json.dumps({
        "total_rows": len(all_rows),
        "years": len(summary),
        "fields": len(fields),
        "out": str(OUT),
    }, indent=2))

if __name__ == "__main__":
    main()
