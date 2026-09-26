#!/usr/bin/env python3
"""Read-only PropLine snapshots for a simulated CLV research pilot.

GitHub Actions writes isolated gzip snapshots to the private tbt-data repository.
No orders, bets, predictions, UI updates, or production data mutations.
"""
import base64
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.prop-line.com/v1"
GH_API = "https://api.github.com"
DATA_REPO = os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")
ROOT = "research/propline_clv"
PROPL = os.getenv("PROPL", "").strip()
GH_TOKEN = os.getenv("TBT_DATA_GH_TOKEN", "").strip()
MAX_EVENTS = max(1, min(12, int(os.getenv("CLV_EVENTS_PER_RUN", "12"))))
DAILY_LIMIT = 650  # local conservative calls/day; free tier is 1000
MIN_PROVIDER_REMAINING = 200
MARKETS = ("h2h", "spreads", "totals", "total_games", "total_sets",
           "total_tiebreaks", "player_aces", "player_double_faults",
           "total_aces", "player_games_won")
if not PROPL or not GH_TOKEN:
    sys.exit("Missing PROPL or TBT_DATA_GH_TOKEN")
quota = {}
api_calls = 0

def request_json(url, headers, method="GET", payload=None, missing_ok=False):
    req = urllib.request.Request(url, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            for header in ("X-Daily-Limit", "X-Daily-Used", "X-Daily-Remaining"):
                if response.headers.get(header):
                    quota[header] = response.headers[header]
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if missing_ok and exc.code == 404:
            return None
        # Never log secret-bearing URLs, response bodies or request headers.
        raise RuntimeError(f"HTTP {exc.code} from {urllib.parse.urlsplit(url).path}") from None
    except urllib.error.URLError:
        raise RuntimeError("Provider/network request failed") from None

def prop(path, params=None):
    global api_calls
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        return request_json(url, {"X-API-Key": PROPL, "Accept": "application/json",
                                  "User-Agent": "BlinQ-research-CLV/1.0"})
    finally:
        api_calls += 1

def github(path, method="GET", data=None, missing_ok=False):
    url = GH_API + "/repos/" + DATA_REPO + "/contents/" + path
    return request_json(url, {"Authorization": "Bearer " + GH_TOKEN,
                              "Accept": "application/vnd.github+json",
                              "Content-Type": "application/json",
                              "X-GitHub-Api-Version": "2022-11-28"},
                        method, json.dumps(data).encode() if data is not None else None,
                        missing_ok)

def unpack(data, keys):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return data[key]
    raise ValueError("Unexpected events/markets response shape")

def parse_time(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except (ValueError, TypeError):
        return None

def pick_events(events, now):
    buckets = [[], [], [], []]
    for event in events:
        if not isinstance(event, dict):
            continue
        kickoff = parse_time(event.get("commence_time"))
        event_id = str(event.get("id") or "")
        if kickoff is None or not event_id.isdigit():
            continue
        hours = (kickoff - now).total_seconds() / 3600
        if not 0 < hours <= 48:
            continue
        tier = 0 if any(word in str(event).lower() for word in
                        ('"atp"', '"wta"', 'atp ', 'wta ')) else 1
        bucket = 0 if hours <= 3 else 1 if hours <= 12 else 2 if hours <= 24 else 3
        buckets[bucket].append((tier, kickoff, event_id, event))
    for bucket in buckets:
        bucket.sort(key=lambda item: (item[0], item[1]))
    selected = []
    # Capture both the early price and the approach to kickoff.
    for bucket in buckets:
        selected.extend(bucket[:3])
    if len(selected) < MAX_EVENTS:
        used = {item[2] for item in selected}
        rest = sorted((item for bucket in buckets for item in bucket if item[2] not in used),
                      key=lambda item: (item[0], item[1]))
        selected.extend(rest[:MAX_EVENTS-len(selected)])
    return selected[:MAX_EVENTS], sum(map(len, buckets))

def today_usage(folder):
    entries = github(folder, missing_ok=True) or []
    total = 0
    if not isinstance(entries, list):
        raise ValueError("Unexpected GitHub research folder response")
    for entry in entries:
        filename = entry.get("name") or ""
        if filename.endswith(".json.gz"):
            try:
                total += int(filename.split("-calls-")[1].split(".")[0])
            except (IndexError, ValueError):
                raise RuntimeError("Unrecognized existing CLV snapshot filename") from None
    return total

def save_snapshot(folder, record):
    now = datetime.now(timezone.utc)
    run_id = os.getenv("GITHUB_RUN_ID") or str(int(time.time()))
    name = now.strftime("%H%M%S") + "-" + run_id + "-calls-" + str(api_calls) + ".json.gz"
    payload = gzip.compress(json.dumps(record, ensure_ascii=False,
                                       separators=(",", ":")).encode("utf-8"))
    path = folder + "/" + name
    github(path, method="PUT", data={"message": "research: isolated PropLine CLV snapshots",
                                    "content": base64.b64encode(payload).decode("ascii")})
    return path

def main():
    now = datetime.now(timezone.utc)
    folder = ROOT + "/" + now.strftime("%Y-%m-%d")
    already = today_usage(folder)
    remaining = DAILY_LIMIT - already
    report = {"schema": 1, "captured_at": now.isoformat(), "api_calls": 0,
              "previous_calls_today": already, "quota": {}, "events": [],
              "window_hours": 48, "research_only": True}
    if remaining < 3:
        report["status"] = "Daily local research budget exhausted"
    else:
        try:
            events = unpack(prop("/sports/tennis/events"), ("events", "data", "results"))
            selected, eligible = pick_events(events, now)
            report["board_events"] = len(events)
            report["eligible_upcoming"] = eligible
            # 2 calls/event for discovery + priced lines. No retries.
            for _, kickoff, event_id, event in selected[:min(MAX_EVENTS, (remaining - api_calls)//2)]:
                if int(quota.get("X-Daily-Remaining", "9999")) < MIN_PROVIDER_REMAINING:
                    report["status"] = "Provider quota reserve reached"
                    break
                row = {"event_id": event_id, "commence_time": kickoff.isoformat(),
                       "home_team": event.get("home_team"), "away_team": event.get("away_team"),
                       "tournament": event.get("tournament_name") or event.get("tournament"),
                       "captured_at": datetime.now(timezone.utc).isoformat(),
                       "available_markets": [], "bookmakers": []}
                try:
                    discovery = unpack(prop(f"/sports/tennis/events/{event_id}/markets"),
                                       ("markets", "data", "results"))
                    row["available_markets"] = sorted(
                        {m["key"] for m in discovery if isinstance(m, dict) and m.get("key")})
                    wanted = [name for name in MARKETS if name in row["available_markets"]]
                    if wanted:
                        odds = prop(f"/sports/tennis/events/{event_id}/odds",
                                    {"markets": ",".join(wanted)})
                        row["bookmakers"] = odds.get("bookmakers", []) if isinstance(odds, dict) else []
                except (RuntimeError, ValueError) as exc:
                    row["error"] = str(exc)
                report["events"].append(row)
                time.sleep(0.15)
        except (RuntimeError, ValueError) as exc:
            report["error"] = str(exc)
    report["api_calls"] = api_calls
    report["quota"] = dict(quota)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/propline_clv_snapshot.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    # Always archive even partial data; a failed persistence step fails the workflow.
    path = save_snapshot(folder, report)
    print(f"CLV snapshot: {len(report['events'])} events, {api_calls} calls, "
          f"daily local calls={already+api_calls}/{DAILY_LIMIT}; archived {path}")
    if "error" in report:
        raise RuntimeError(report["error"])

if __name__ == "__main__":
    main()
