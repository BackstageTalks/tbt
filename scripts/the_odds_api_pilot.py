#!/usr/bin/env python3
"""Read-only, low-credit The Odds API tennis totals pilot for BlinQ.

The existing PropLine integration remains primary. Never publish a bet from
an unverified alternate provider. Two runs/day, max 3 tennis sport keys/run,
one region and one market: <=186 credits in any 31-day month.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.the-odds-api.com/v4"
MONTHLY_FREE = 500
HARD_RUN_CAP = 3
MIN_REMAINING = 75


def _get(path: str, params: dict, *, opener=urlopen):
    url = API + path + "?" + urlencode(params)
    try:
        with opener(Request(url, headers={"Accept": "application/json",
                                           "User-Agent": "BlinQ-tennis-odds-pilot/1"}), timeout=17) as reply:
            return json.load(reply), {
                "remaining": _int_header(reply.headers, "x-requests-remaining"),
                "used": _int_header(reply.headers, "x-requests-used"),
                "last": _int_header(reply.headers, "x-requests-last"),
            }
    except HTTPError as exc:
        # Never leak the API key embedded in the query string.
        raise RuntimeError(f"The Odds API HTTP {exc.code}") from None
    except (URLError, TimeoutError):
        raise RuntimeError("The Odds API request timed out or failed") from None


def _int_header(headers, name):
    raw = headers.get(name)
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _rank_tennis_sport(s):
    title = str(s.get("title") or "").lower()
    key = str(s.get("key") or "").lower()
    if "atp" in key or "atp" in title:
        return 0
    if "wta" in key or "wta" in title:
        return 1
    return 2


def _markets(events):
    """Sample actual bookmaker markets without asserting totals means games."""
    prices = []
    listed = 0
    for event in events if isinstance(events, list) else []:
        for book in event.get("bookmakers") or []:
            for market in book.get("markets") or []:
                if market.get("key") != "totals":
                    continue
                listed += 1
                groups = {}
                for outcome in market.get("outcomes") or []:
                    side = str(outcome.get("name") or "").lower()
                    try:
                        point, price = float(outcome.get("point")), float(outcome.get("price"))
                    except (TypeError, ValueError):
                        continue
                    if side in ("over", "under") and 1.01 < price < 100 and 0 < point < 100:
                        groups.setdefault(point, {})[side] = price
                for line, sides in groups.items():
                    if "over" not in sides or "under" not in sides:
                        continue
                    if len(prices) < 12:
                        prices.append({
                            "event_id": event.get("id"),
                            "players": [event.get("home_team"), event.get("away_team")],
                            "commence_time": event.get("commence_time"),
                            "bookmaker": book.get("title") or book.get("key"),
                            "line": line, "over": sides["over"], "under": sides["under"],
                            # Contract pending: even plausible 19.5 may not
                            # be match-total games at every bookmaker.
                            "contract_verified": False,
                        })
    return listed, prices


def collect(*, key, now=None, run_cap=HARD_RUN_CAP, opener=urlopen):
    now = now or datetime.now(timezone.utc)
    if not 0 <= run_cap <= HARD_RUN_CAP:
        raise ValueError("run_cap must be 0..3")
    report = {
        "schema": 1, "captured_at": now.isoformat(), "source": "the-odds-api",
        "region": "eu", "market": "totals", "format": "decimal",
        "published_bets": 0, "research_only": True,
        "sports_checked": [], "requests_made": 0,
        "credits_spent": 0, "credits_remaining": None,
        "matched_games": 0, "sample_market_quotes": [],
        "status": "ok",
    }
    if not key or not run_cap:
        report["status"] = "skipped_no_secret_or_disabled"
        return report
    sports, quota = _get("/sports/", {"apiKey": key}, opener=opener)
    if quota["remaining"] is not None and quota["remaining"] <= MIN_REMAINING:
        report["status"] = "quota_reserve"
        report["credits_remaining"] = quota["remaining"]
        return report
    if quota["used"] is not None and quota["used"] >= 400:
        report["status"] = "monthly_budget_stop"
        report["credits_remaining"] = quota["remaining"]
        return report
    active = [s for s in sports if isinstance(s, dict) and s.get("active") and
              str(s.get("group") or "").lower() == "tennis" and
              not s.get("has_outrights")]
    active.sort(key=lambda s: (_rank_tennis_sport(s), str(s.get("key"))))
    # Rotate the available tournament keys over the month to expand coverage.
    if active:
        window = (now.timetuple().tm_yday * 2 + (1 if now.hour >= 12 else 0)) * run_cap
        offset = window % len(active)
        active = (active[offset:] + active[:offset])[:run_cap]
    for sport in active:
        if report["credits_remaining"] is not None and report["credits_remaining"] <= MIN_REMAINING:
            report["status"] = "quota_reserve"
            break
        # Endpoint returns ALL events for the tournament in one market/region;
        # never issue per-event odds queries.
        event_data, q = _get(f"/sports/{sport['key']}/odds/",
                             {"apiKey": key, "regions": "eu", "markets": "totals",
                              "oddsFormat": "decimal"}, opener=opener)
        report["requests_made"] += 1
        cost = q["last"] if q["last"] is not None else 1
        if cost < 0 or cost > 1:
            report["status"] = "unexpected_request_cost"
            break
        report["credits_spent"] += cost
        report["credits_remaining"] = q["remaining"]
        listed, quotes = _markets(event_data)
        report["sports_checked"].append({
            "sport": sport.get("key"), "event_count": len(event_data) if isinstance(event_data, list) else 0,
            "bookmaker_totals": listed, "complete_samples": len(quotes),
            "credits": cost,
        })
        report["sample_market_quotes"].extend(quotes[:max(0, 12 - len(report["sample_market_quotes"]))])
        # Fails closed on absent headers once free-tier budget is ambiguous.
        if q["remaining"] is None or q["used"] is None:
            report["status"] = "unknown_quota_stop"
            break
        if q["remaining"] <= MIN_REMAINING or q["used"] >= 400:
            report["status"] = "quota_reserve_or_budget"
            break
    return report


def main():
    report = collect(key=os.getenv("THE_ODDS_API_KEY", "").strip(),
                     run_cap=int(os.getenv("THE_ODDS_MAX_SPORTS", "3")))
    target = Path("reports/the_odds_api_pilot.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # Print only metadata; API key never leaves the GitHub secret.
    print(json.dumps({k: v for k, v in report.items() if k != "sample_market_quotes"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
