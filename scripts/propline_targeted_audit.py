#!/usr/bin/env python3
"""Manual, read-only audit of future PropLine tennis markets.

Separates advertised markets from actual bookmaker outcomes and keeps odds
lines in the JSON. Never emits the API key or changes production data.
"""
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
KEY = os.getenv("PROPL", "").strip()
if not KEY:
    sys.exit("Missing secret PROPL")
MAX_EVENTS = max(1, min(30, int(os.getenv("PROPLINE_MAX_EVENTS", "20"))))
MAX_HOURS = max(1, min(168, int(os.getenv("PROPLINE_WINDOW_HOURS", "72"))))
MARKETS = ("h2h", "spreads", "totals", "total_games", "total_sets",
           "player_aces", "player_double_faults", "total_aces",
           "total_tiebreaks", "player_games_won")
quota = {}
calls = 0

def fetch(path, params=None):
    global calls
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"X-API-Key": KEY, "Accept": "application/json",
                      "User-Agent": "BlinQ-read-only-market-audit/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            calls += 1
            for header in ("X-Daily-Limit", "X-Daily-Used", "X-Daily-Remaining"):
                if response.headers.get(header):
                    quota[header] = response.headers[header]
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} at {path}") from None
    except urllib.error.URLError:
        raise RuntimeError(f"Network error at {path}") from None

def items(data, keys):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
    raise ValueError("Unexpected API response structure")

def parse_time(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (TypeError, ValueError):
        return None

def label(event):
    return str(event.get("tournament_name") or event.get("tournament") or
               event.get("league") or event.get("sport_title") or
               event.get("sport_key") or "")

def inspect_odds(data):
    markets = {}
    bookmaker_list = data.get("bookmakers") or [] if isinstance(data, dict) else []
    for bookmaker in bookmaker_list:
        if not isinstance(bookmaker, dict):
            continue
        book_name = str(bookmaker.get("title") or bookmaker.get("key") or
                        bookmaker.get("name") or "unknown")
        for market in bookmaker.get("markets") or []:
            if not isinstance(market, dict):
                continue
            key = market.get("key")
            if not key:
                continue
            bucket = markets.setdefault(key, {"bookmakers": [], "outcome_count": 0,
                                               "sample_lines": []})
            if book_name not in bucket["bookmakers"]:
                bucket["bookmakers"].append(book_name)
            for outcome in market.get("outcomes") or []:
                if not isinstance(outcome, dict):
                    continue
                price = outcome.get("price")
                if price is None:
                    continue
                bucket["outcome_count"] += 1
                if len(bucket["sample_lines"]) < 6:
                    bucket["sample_lines"].append({
                        "bookmaker": book_name,
                        "name": outcome.get("name"),
                        "description": outcome.get("description"),
                        "point": outcome.get("point"),
                        "price": price
                    })
    return markets, len(bookmaker_list)

def main():
    now = datetime.now(timezone.utc)
    events = items(fetch("/sports/tennis/events"), ("events", "data", "results"))
    candidates = []
    past_or_invalid = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        when = parse_time(event.get("commence_time"))
        event_id = str(event.get("id") or "")
        if when is None or when <= now or (when - now).total_seconds() > MAX_HOURS * 3600:
            past_or_invalid += 1
            continue
        if not event_id.isdigit():
            continue
        tournament = label(event)
        tier = 0 if any(s in tournament.lower() for s in ("atp", "wta")) else 1
        candidates.append((tier, when, event_id, tournament, event))
    candidates.sort(key=lambda x: (x[0], x[1]))
    report = {
        "audit_version": 2, "created_at_utc": now.isoformat(),
        "on_board": len(events), "past_outside_window_or_invalid": past_or_invalid,
        "eligible_upcoming": len(candidates), "selected_count": min(MAX_EVENTS, len(candidates)),
        "window_hours": MAX_HOURS, "max_events": MAX_EVENTS, "events": [],
        "quota": {}, "api_calls": 0
    }
    for _, when, event_id, tournament, event in candidates[:MAX_EVENTS]:
        row = {"id": event_id, "tournament": tournament,
               "commence_time": when.isoformat(),
               "home_team": event.get("home_team"),
               "away_team": event.get("away_team"),
               "available_markets": [], "priced_markets": {},
               "bookmaker_count": 0}
        try:
            discovery = items(fetch(f"/sports/tennis/events/{event_id}/markets"),
                              ("markets", "data", "results"))
            available = sorted({m.get("key") for m in discovery
                                if isinstance(m, dict) and m.get("key")})
            row["available_markets"] = available
            wanted = [m for m in MARKETS if m in available]
            if wanted:
                result = fetch(f"/sports/tennis/events/{event_id}/odds",
                               {"markets": ",".join(wanted)})
                row["priced_markets"], row["bookmaker_count"] = inspect_odds(result)
                row["requested_markets"] = wanted
        except (RuntimeError, ValueError) as exc:
            row["error"] = str(exc)
        report["events"].append(row)
        if int(quota.get("X-Daily-Remaining", "9999")) < 20:
            report["stopped_early"] = "Insufficient daily quota remaining"
            break
        time.sleep(0.2)
    report["quota"] = dict(quota)
    report["api_calls"] = calls
    observed = set(MARKETS)
    for event in report["events"]:
        observed.update(event["available_markets"])
        observed.update(event["priced_markets"])
    report["summary"] = {
        market: {"advertised": sum(market in e["available_markets"]
                                   for e in report["events"]),
                 "priced": sum(e["priced_markets"].get(market, {}).get("outcome_count", 0) > 0
                               for e in report["events"])}
        for market in sorted(observed)
    }
    Path("reports").mkdir(exist_ok=True)
    destination = Path("reports/propline_targeted_audit.json")
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(f"On board: {len(events)} | upcoming in {MAX_HOURS}h: {len(candidates)} "
          f"| audited: {len(report['events'])} | calls: {calls}")
    for name, stats in report["summary"].items():
        print(f"{name}: advertised={stats['advertised']} priced={stats['priced']}")
    print(f"Saved {destination}")
    if not candidates:
        print("No upcoming events in window; no per-event requests were made.")

if __name__ == "__main__":
    main()
