#!/usr/bin/env python3
"""Offline simulated CLV report from private PropLine snapshot archives."""
import base64
import gzip
import json
import os
import statistics
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")
TOKEN = os.getenv("TBT_DATA_GH_TOKEN", "").strip()
ROOT = "research/propline_clv"

def gh_contents(path):
    if not TOKEN:
        raise RuntimeError("Missing TBT_DATA_GH_TOKEN")
    req = urllib.request.Request(
        "https://api.github.com/repos/" + REPO + "/contents/" + path,
        headers={"Authorization": "Bearer " + TOKEN,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError("GitHub archive fetch HTTP " + str(exc.code)) from None

def read_archives(days):
    now = datetime.now(timezone.utc)
    for offset in range(days):
        day = (now - timedelta(days=offset)).date().isoformat()
        folder = gh_contents(ROOT + "/" + day) or []
        for entry in folder:
            if not entry.get("name", "").endswith(".json.gz"):
                continue
            obj = gh_contents(entry["path"])
            if obj and obj.get("content"):
                yield json.loads(gzip.decompress(base64.b64decode(
                    obj["content"].replace("\n", ""))))

def decimal(price):
    try:
        price = float(price)
        if price >= 10:
            return 1 + price / 100
        if price <= -10:
            return 1 + 100 / abs(price)
        if 1.001 <= price < 10:
            return price
    except (TypeError, ValueError):
        return None
    return None

def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None

def _market_stats(rows):
    result = {}
    for market in sorted({row["market"] for row in rows}):
        values = [
            row["observed_clv_percent"]
            for row in rows
            if row["market"] == market
        ]
        result[market] = {
            "comparable_selections": len(values),
            "median_observed_clv_percent": round(statistics.median(values), 3),
            "positive_share": round(sum(x > 0 for x in values) / len(values), 3),
        }
    return result


def evaluate(snapshots):
    series = defaultdict(list)
    series_priority = {}
    observed_matches = set()
    observed_blinq_matches = set()
    calls = 0
    for snap in snapshots:
        calls += snap.get("api_calls", 0)
        for event in snap.get("events", []):
            kickoff = parse_time(event.get("commence_time"))
            observed = parse_time(event.get("captured_at"))
            event_id = event.get("event_id")
            if not kickoff or not observed or observed >= kickoff:
                continue
            observed_matches.add(event_id)
            priority = bool(event.get("blinq_priority"))
            if priority:
                observed_blinq_matches.add(event_id)
            for book in event.get("bookmakers", []):
                book_id = book.get("key") or book.get("title") or book.get("name")
                for market in book.get("markets", []):
                    market_id = market.get("key")
                    if market_id not in ("h2h", "spreads", "totals", "total_games",
                                         "total_sets", "total_tiebreaks"):
                        continue
                    for outcome in market.get("outcomes", []):
                        odds = decimal(outcome.get("price"))
                        if odds is None:
                            continue
                        # Same point & side, same bookmaker: never compare unlike lines.
                        key = (event_id, book_id, market_id,
                               str(outcome.get("name")), str(outcome.get("description")),
                               str(outcome.get("point")))
                        series[key].append((observed, kickoff, odds))
                        series_priority[key] = bool(series_priority.get(key) or priority)

    moves = []
    near_close_count = 0
    near_close_blinq_count = 0
    for key, observations in series.items():
        observations.sort(key=lambda row: row[0])
        kickoff = observations[0][1]
        early = [row for row in observations
                 if timedelta(hours=2) <= kickoff - row[0] <= timedelta(hours=36)]
        late = [row for row in observations
                if timedelta(0) < kickoff - row[0] <= timedelta(minutes=90)]
        priority = bool(series_priority.get(key))
        if late:
            near_close_count += 1
            if priority:
                near_close_blinq_count += 1
        if not early or not late:
            continue
        entry, closing = early[0], late[-1]
        if closing[0] <= entry[0]:
            continue
        # Pure line movement proxy: not a placed bet or bookmaker's official close.
        moves.append({
            "event_id": key[0],
            "bookmaker": key[1],
            "market": key[2],
            "outcome": key[3],
            "description": key[4],
            "point": key[5],
            "blinq_priority": priority,
            "entry_time": entry[0].isoformat(),
            "closing_sample_time": closing[0].isoformat(),
            "entry_decimal": round(entry[2], 4),
            "late_decimal": round(closing[2], 4),
            "observed_clv_percent": round(100 * (entry[2] / closing[2] - 1), 3),
        })

    blinq_moves = [row for row in moves if row["blinq_priority"]]
    return {
        "method": "unweighted observed line movement proxy, NOT actual bet CLV",
        "limits": [
            "One sample per hour approximates rather than establishes true close.",
            "Only identical bookmaker, selection and point are compared.",
            "Entries are earliest observed 2-36h before kickoff; closing proxy is "
            "last observed within 90 minutes before kickoff.",
            "blinq_priority means the event matched the current BlinQ daily offer; "
            "movement remains evaluation-only and is not evidence of edge by itself.",
        ],
        "archived_api_calls": calls,
        "unique_events": len(observed_matches),
        "blinq_priority_events": len(observed_blinq_matches),
        "observed_market_selection_series": len(series),
        "selection_series_with_near_close_sample": near_close_count,
        "blinq_series_with_near_close_sample": near_close_blinq_count,
        "comparable_series": len(moves),
        "blinq_comparable_series": len(blinq_moves),
        "by_market": _market_stats(moves),
        "blinq_by_market": _market_stats(blinq_moves),
        "blinq_examples": blinq_moves[:60],
        "examples": moves[:60],
    }

def main():
    days = max(1, min(int(os.getenv("CLV_LOOKBACK_DAYS", "3")), 7))
    snapshots = list(read_archives(days))
    result = evaluate(snapshots)
    result["archive_files"] = len(snapshots)
    result["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    Path("reports").mkdir(exist_ok=True)
    output = Path("reports/propline_clv_report.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CLV research report: {len(snapshots)} archives, "
          f"{result['archived_api_calls']} provider calls, "
          f"{result['comparable_series']} comparable price moves.")
    for market, stats in result["by_market"].items():
        print(market, stats)

if __name__ == "__main__":
    main()
