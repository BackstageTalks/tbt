#!/usr/bin/env python3
"""Bounded read-only pilot of a SECOND RapidAPI tennis provider (50/day plan).

Deliberately independent of BlinQ's existing 15k-request Tennis API. No
production odds, ledger, picks or data are modified. Manual dispatch only.
"""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOST = "tennis-api-atp-wta-itf.p.rapidapi.com"
BASE = "https://" + HOST + "/tennis/v2"
MAX_REQUESTS = 8   # explicit single test <= 8 / 50 daily requests
MAX_EVENTS = 6
# Only exact market contracts, do not infer ACES or DF from unknown labels.
INTEREST = ("ace", "double fault", "total game", "total set", "over under", "most ace")


def preview(payload):
    """Summarize only metadata and market names, never guess contract meaning."""
    if not isinstance(payload, dict):
        return {"response_type": type(payload).__name__}
    body = payload.get("results", payload.get("result", {}))
    markets = list(body.keys()) if isinstance(body, dict) else []
    if isinstance(body, list):
        markets = sorted({str(m.get("market") or m.get("name") or "")
                          for m in body if isinstance(m, dict)})
    focused = [str(m) for m in markets if any(term in str(m).lower() for term in INTEREST)]
    return {"success": payload.get("success"), "market_count": len(markets),
            "market_names": [str(m)[:100] for m in markets[:70]],
            "relevant_markets": focused[:45],
            "error_message": str(payload.get("message") or "")[:100]}


class Client:
    def __init__(self, key, limit=MAX_REQUESTS, opener=urllib.request.urlopen):
        self.key = key
        self.limit = min(MAX_REQUESTS, max(0, int(limit)))
        self.count = 0
        self.opener = opener
        self.provider_remaining = None

    def get(self, path):
        if self.count >= self.limit:
            raise RuntimeError("local_request_limit")
        self.count += 1   # failed attempts still count
        req = urllib.request.Request(BASE + path, headers={
            "X-RapidAPI-Key": self.key, "X-RapidAPI-Host": HOST,
            "Accept": "application/json", "User-Agent": "BlinQ-tennis-api-50day-pilot/1",
        })
        try:
            with self.opener(req, timeout=16) as res:
                remaining = res.headers.get("x-ratelimit-requests-remaining")
                if remaining is not None:
                    try:
                        self.provider_remaining = int(remaining)
                    except ValueError:
                        pass
                return json.load(res)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"RapidAPI HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError("RapidAPI network request failed") from None


def _events(data):
    if not isinstance(data, dict):
        return []
    result = data.get("results", data.get("result", []))
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for k in ("events", "data", "results"):
            if isinstance(result.get(k), list):
                return result[k]
    return []


def _time(row):
    try:
        ts = row.get("startTimestamp")
        if ts:
            return datetime.fromtimestamp(int(ts), timezone.utc)
        raw = str(row.get("startTime") or row.get("start") or
                  row.get("commence_time") or "").replace("Z", "+00:00")
        result = datetime.fromisoformat(raw)
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def run(client, *, now=None):
    now = now or datetime.now(timezone.utc)
    report = {"schema": 1, "audit_time": now.isoformat(), "read_only": True,
              "odds_plan_requirement": "ULTRA_or_MEGA",
              "quota": "50 requests/day", "request_cap": client.limit,
              "requests_used": 0, "provider_remaining": None,
              "upcoming": {}, "checked_events": [], "status": "ok"}
    # ATP and WTA board discovery: 2 calls, 50 rows per page; sample only the
    # first page on each tour rather than spending on broad pagination.
    board = []
    for tour in ("atp", "wta"):
        try:
            result = client.get(f"/upcoming/matches/{tour}?group=singles&limit=30&page=1")
            candidates = _events(result)
            report["upcoming"][tour] = {
                "count_on_first_page": len(candidates),
                "total": (result.get("pagination") or {}).get("total") if isinstance(result, dict) else None,
                "success": result.get("success") if isinstance(result, dict) else None,
            }
            for row in candidates:
                if not isinstance(row, dict):
                    continue
                eid = str(row.get("liveEventId") or row.get("live_event_id") or "")
                start = _time(row)
                if re.fullmatch(r"[0-9]+", eid) and (start is None or start > now):
                    board.append((tour, eid, row, start))
        except RuntimeError as err:
            report["upcoming"][tour] = {"error": str(err)}
            # 401/403 is a subscription issue; no point burning the rest.
            if "401" in str(err) or "403" in str(err):
                report["status"] = "key_or_subscription_required"
                break
        if client.provider_remaining is not None and client.provider_remaining <= 5:
            report["status"] = "provider_daily_reserve"
            break

    # Only query odds if the schedule gives an explicit LIVE event ID. Core
    # fixture IDs must never be sent to live-odds endpoints. Under the BASIC
    # 50/day tier, provider docs restrict odds to ULTRA/MEGA, so a 403 is
    # expected; stop rather than consuming more calls.
    # Scope down to one event per tour first, then fill up to max 6. Do not
    # fetch duplicate IDs or use unrelated fixture IDs from the other API.
    board.sort(key=lambda x: (x[3] or now, x[0], x[1]))
    selected = []
    used = set()
    for tour in ("atp", "wta"):
        choice = next((x for x in board if x[0] == tour and x[1] not in used), None)
        if choice:
            selected.append(choice)
            used.add(choice[1])
    for row in board:
        if len(selected) >= MAX_EVENTS:
            break
        if row[1] not in used:
            selected.append(row)
            used.add(row[1])
    if report["status"] == "ok":
        for tour, event_id, row, start in selected:
            if client.count >= client.limit:
                break
            if client.provider_remaining is not None and client.provider_remaining <= 5:
                report["status"] = "provider_daily_reserve"
                break
            try:
                data = client.get("/extend/api/event/odds/latest-all/" + event_id)
                report["checked_events"].append({
                    "id": event_id, "tour": tour,
                    "start": start.isoformat() if start else None,
                    "player_names": [
                        str(row.get(k) or "")[:80]
                        for k in ("home_team", "away_team")
                    ],
                    "odds": preview(data),
                })
            except RuntimeError as err:
                report["checked_events"].append({
                    "id": event_id, "tour": tour, "error": str(err),
                })
                if "403" in str(err) or "401" in str(err):
                    report["status"] = "odds_not_in_current_subscription"
                    break
    if report["status"] == "ok" and not selected:
        report["status"] = "no_explicit_live_event_ids_from_schedule"
    report["requests_used"] = client.count
    report["provider_remaining"] = client.provider_remaining
    return report


if __name__ == "__main__":
    secret = os.getenv("RAPIDAPI_KEY", "").strip()
    if not secret:
        raise SystemExit("RAPIDAPI_KEY secret missing")
    result = run(Client(secret))
    out = Path("reports/tennis_api_alt_50day.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
