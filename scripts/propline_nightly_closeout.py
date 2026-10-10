#!/usr/bin/env python3
"""Research-only PropLine closeout (external dispatch, no cron).

Collection contract:
  1) All future tennis events with complete numeric IDs; no identity guessing.
  2) Discover markets per event; pull exactly one all-relevant-markets odds snapshot.
  3) Prioritize double faults, aces, h2h, games, sets, then CLV snapshots.
  4) Preserve unmodified provider payload + UTC capture time + provider event ID.
  5) Flush immutable batches every 25 attempted requests; read back blob SHA/size.
  6) Never promote, train, import to CDB, or modify publication.
"""
import base64
import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.prop-line.com/v1"
REPO = os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data")
ROOT = "research/propline_closeout"
KEY = os.getenv("PROPL", "")
TOKEN = os.getenv("TBT_DATA_GH_TOKEN", "")
MAX_CALLS = min(750, max(0, int(os.getenv("CLOSEOUT_MAX_REQUESTS", "750"))))
BATCH_SIZE = 25
MARKETS = ("player_double_faults", "player_aces", "h2h", "total_games",
           "totals", "total_sets", "spreads", "player_games_won")
WAIT = 0.5
STATE = {"calls": 0, "remaining": None, "reason": "", "batches": 0}
DATA = []


def now():
    return datetime.now(timezone.utc)


def allowed(t):
    # 23:00 Europe/Bratislava = 21:00 UTC (summer) or 22:00 UTC (winter).
    # Conservative latest cutoff 23:55 UTC; never cross midnight quota reset.
    return t.hour in (21, 22) or (t.hour == 23 and t.minute < 55)


def blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def github(path, method="GET", content=None, optional=False):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents/{path}", data=content,
        method=method, headers={"Authorization": "Bearer " + TOKEN,
          "Accept": "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if optional and exc.code == 404:
            return None
        raise RuntimeError("GitHub persistence HTTP " + str(exc.code)) from None


def save(day, runid):
    if not DATA:
        return
    n = STATE["batches"]
    filename = f"{runid}-batch-{n:04d}.json.gz"
    path = f"{ROOT}/{day}/{filename}"
    record = {"schema": 1, "day_utc": day, "run_id": runid,
              "records": DATA, "attempted_calls_at_save": STATE["calls"],
              "created_at_utc": now().isoformat(), "research_only": True}
    raw = gzip.compress(json.dumps(record, ensure_ascii=False, sort_keys=True).encode())
    Path("reports").mkdir(exist_ok=True)
    local = Path("reports") / filename
    local.write_bytes(raw)
    expected = blob_sha(raw)
    previous = github(path, optional=True)
    if previous is None:
        body = json.dumps({"message": "research: PropLine closeout batch",
                           "content": base64.b64encode(raw).decode()}).encode()
        try:
            github(path, method="PUT", content=body)
        except RuntimeError:
            pass  # Read-back decides whether an uncertain write succeeded.
    result = github(path, optional=True)
    if not result or result.get("sha") != expected or result.get("size") != len(raw):
        raise RuntimeError("Batch integrity/read-back FAILED: " + path)
    STATE["batches"] += 1
    print(json.dumps({"saved": path, "items": len(DATA),
                      "calls": STATE["calls"]}), flush=True)
    DATA.clear()


def flush_if_needed(day, runid):
    if len(DATA) >= BATCH_SIZE:
        save(day, runid)


def request(path, params=None):
    if STATE["calls"] >= MAX_CALLS:
        STATE["reason"] = "run_cap"
        return None
    if not allowed(now()):
        STATE["reason"] = "quota_reset_cutoff"
        return None
    if STATE["remaining"] is not None and STATE["remaining"] <= 0:
        STATE["reason"] = "daily_quota_exhausted"
        return None
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    retries = 0
    while True:
        if not allowed(now()) or STATE["calls"] >= MAX_CALLS:
            STATE["reason"] = "cutoff_or_run_cap"
            return None
        STATE["calls"] += 1
        time.sleep(WAIT)
        req = urllib.request.Request(url, headers={
            "X-API-Key": KEY, "Accept": "application/json",
            "User-Agent": "BlinQ-nightly-closeout/1"})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                remaining = resp.headers.get("X-Daily-Remaining")
                reset = resp.headers.get("X-Daily-Reset")
                if remaining is None or reset is None:
                    STATE["reason"] = "missing_quota_headers"
                    return None
                STATE["remaining"] = int(remaining)
                # Never allow crossing the provider's own reset time.
                if int(reset) <= int(time.time()):
                    STATE["reason"] = "provider_reset"
                    return None
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            rem = exc.headers.get("X-Daily-Remaining")
            if rem is not None:
                STATE["remaining"] = int(rem)
            if exc.code == 429:
                retry = exc.headers.get("Retry-After", "1")
                try:
                    seconds = float(retry)
                except ValueError:
                    seconds = 2
                if STATE["remaining"] == 0 or seconds > 60:
                    STATE["reason"] = "daily_quota_exhausted"
                    return None
                if retries < 3 and seconds <= 10:
                    retries += 1
                    time.sleep(max(1, seconds))
                    continue
                STATE["reason"] = "burst_throttle"
            else:
                STATE["reason"] = "provider_http_" + str(exc.code)
            return None
        except (urllib.error.URLError, TimeoutError):
            STATE["reason"] = "provider_network_error"
            return None


def unpack(data, names):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for name in names:
            if isinstance(data.get(name), list):
                return data[name]
    raise ValueError("Invalid provider list shape")


def collect():
    if not KEY or not TOKEN:
        raise RuntimeError("Missing PROPL/TBT_DATA_GH_TOKEN")
    started = now()
    if not allowed(started):
        raise RuntimeError("Outside protected closeout window (21:00-23:55 UTC)")
    day = started.date().isoformat()
    runid = os.getenv("GITHUB_RUN_ID", str(int(started.timestamp())))
    try:
        board = request("/sports/tennis/events")
        if board is None:
            return
        events = unpack(board, ("events", "data", "results"))
        future = []
        for e in events:
            if not isinstance(e, dict) or not str(e.get("id", "")).isdigit():
                continue
            try:
                kickoff = datetime.fromisoformat(str(e.get("commence_time", "")).replace("Z", "+00:00"))
                if kickoff.tzinfo is None:
                    kickoff = kickoff.replace(tzinfo=timezone.utc)
                if kickoff <= started:
                    continue
            except ValueError:
                continue
            # Include up to seven future days; nearer fixtures take precedence.
            if (kickoff-started).total_seconds() <= 7 * 24 * 3600:
                future.append((kickoff, e))
        future.sort(key=lambda item: item[0])
        print(json.dumps({"eligible_events": len(future), "budget": MAX_CALLS, "scope_days": 7}), flush=True)
        discovered = []
        for kickoff, event in future:
            if STATE["reason"] or STATE["calls"] >= max(1, (MAX_CALLS - 1) // 2):
                break
            eid = str(event["id"])
            markets = request(f"/sports/tennis/events/{eid}/markets")
            if markets is None:
                break
            try:
                keys = set(m.get("key") for m in unpack(markets, ("markets", "data", "results"))
                           if isinstance(m, dict))
            except ValueError:
                STATE["reason"] = "invalid_market_shape"
                break
            wanted = [m for m in MARKETS if m in keys]
            discovered.append((kickoff, event, keys, wanted))
        # Spend odds calls on sparse player props first. More than one category
        # in the same odds request costs no extra API call.
        discovered.sort(key=lambda x: (
            0 if "player_double_faults" in x[2] else
            1 if "player_aces" in x[2] else
            2 if "h2h" in x[2] else
            3 if ({"total_games", "totals", "total_sets"} & x[2]) else 4,
            x[0]))
        for kickoff, event, keys, wanted in discovered:
            if STATE["reason"]:
                break
            eid = str(event["id"])
            # Keep one discovery record even when no desired market is offered.
            snapshot = {"event_id": eid, "event": event, "commence_time": kickoff.isoformat(),
                        "captured_at_utc": now().isoformat(),
                        "available_markets": sorted(k for k in keys if isinstance(k, str)),
                        "requested_markets": wanted, "odds": None}
            if wanted and STATE["calls"] < MAX_CALLS:
                snapshot["odds"] = request(f"/sports/tennis/events/{eid}/odds",
                                           {"markets": ",".join(wanted)})
            DATA.append(snapshot)
            flush_if_needed(day, runid)
            if STATE["reason"]:
                break
        if not STATE["reason"]:
            STATE["reason"] = "useful_slate_exhausted"
    finally:
        save(day, runid)
        print(json.dumps({"summary": STATE, "records_pending": len(DATA)}), flush=True)


if __name__ == "__main__":
    collect()
