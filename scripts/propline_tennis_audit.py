#!/usr/bin/env python3
"""Read-only PropLine tennis market coverage audit. No third-party dependencies."""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api.prop-line.com/v1"
MARKETS = ("h2h", "spreads", "totals", "total_sets", "player_aces",
           "player_double_faults", "total_aces", "total_tiebreaks",
           "player_games_won")
MAX_EVENTS = max(1, min(int(os.getenv("PROPLINE_MAX_EVENTS", "10")), 20))
API_KEY = os.environ.get("PROPL", "").strip()
if not API_KEY:
    sys.exit("PROPL repository secret is missing")
quota = {}

def fetch(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "X-API-Key": API_KEY, "Accept": "application/json",
        "User-Agent": "BlinQ-PropLine-audit/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            for name in ("X-Daily-Limit", "X-Daily-Used", "X-Daily-Remaining"):
                if resp.headers.get(name):
                    quota[name] = resp.headers[name]
            return json.load(resp)
    except urllib.error.HTTPError as err:
        # Never include the response body, request URL or API key in logs.
        raise RuntimeError(f"HTTP {err.code} at {path}") from None
    except urllib.error.URLError:
        raise RuntimeError(f"Network error at {path}") from None

def event_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("events", "data", "results"):
            if isinstance(data.get(key), list):
                return data[key]
    raise ValueError("Unexpected events API response shape")

def markets_list(data):
    if isinstance(data, list):
        return [x.get("key") for x in data if isinstance(x, dict) and x.get("key")]
    if isinstance(data, dict):
        for key in ("markets", "data", "results"):
            if isinstance(data.get(key), list):
                return markets_list(data[key])
    raise ValueError("Unexpected markets API response shape")

def market_counts(data):
    counts = Counter()
    books = data.get("bookmakers") or [] if isinstance(data, dict) else []
    for book in books:
        for market in book.get("markets") or []:
            if isinstance(market, dict) and market.get("key"):
                counts[market["key"]] += len(market.get("outcomes") or [])
    return dict(counts), len(books)

def main():
    events = event_list(fetch("/sports/tennis/events"))
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "events_on_board": len(events), "requested_events": MAX_EVENTS,
        "market_keys_requested": list(MARKETS), "events": [],
        "quota": {}
    }
    for event in events:
        if len(report["events"]) >= MAX_EVENTS:
            break
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "").strip()
        if not event_id or not event_id.isdigit():
            continue
        row = {
            "id": event_id, "home_team": event.get("home_team"),
            "away_team": event.get("away_team"),
            "commence_time": event.get("commence_time"),
            "available_markets": [], "outcomes_by_market": {}, "bookmakers": 0
        }
        try:
            available = markets_list(fetch(
                f"/sports/tennis/events/{event_id}/markets"))
            row["available_markets"] = available
            wanted = [m for m in MARKETS if m in available]
            if wanted:
                data = fetch(f"/sports/tennis/events/{event_id}/odds",
                             {"markets": ",".join(wanted)})
                row["outcomes_by_market"], row["bookmakers"] = market_counts(data)
        except (RuntimeError, ValueError) as exc:
            row["error"] = str(exc)
        report["events"].append(row)
        if int(quota.get("X-Daily-Remaining", "9999")) < 5:
            report["stopped_early"] = "Quota almost exhausted"
            break
        time.sleep(0.25)
    report["quota"] = dict(quota)
    coverage = Counter(m for e in report["events"]
                       for m in set(e["available_markets"]))
    report["summary"] = {
        m: {
            "events_listing_market": coverage[m],
            "events_with_outcomes": sum(
                e["outcomes_by_market"].get(m, 0) > 0 for e in report["events"])
        } for m in MARKETS
    }
    Path("reports").mkdir(exist_ok=True)
    out = Path("reports/propline_tennis_audit.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"Audited {len(report['events'])} events; on board: {len(events)}")
    for market, count in report["summary"].items():
        print(f"{market}: discovered={count['events_listing_market']}; "
              f"priced={count['events_with_outcomes']}")
    print(f"Report: {out}")

if __name__ == "__main__":
    main()
