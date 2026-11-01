#!/usr/bin/env python3
"""Read-only, shared-budget TennisApi contract probe; never writes canonical CDB.

Run only with the existing guarded RapidTennisClient and bounded provider quota.
Raw payloads are hashed; report contains only structural metadata and counts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tbt.providers.rapidapi import RapidTennisClient
from tbt.providers.tennisapi_extra import point_by_point_inventory


def _obj(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _nested_int(value: Any, *path: str) -> int | None:
    for name in path:
        value = _obj(value).get(name)
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
        return result if result > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def summarize(name: str, payload: Any, *, event_id: int) -> dict:
    """Strict, bounded observation; no guesswork about betting price timestamps."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    result = {
        "state": "available" if payload not in ({}, None, []) else "no_content",
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "payload_bytes": len(raw),
        "top_keys": sorted(payload)[:30] if isinstance(payload, dict) else [],
        "shape": type(payload).__name__,
    }
    obj = _obj(payload)
    if name == "event_odds":
        markets = obj.get("markets")
        if isinstance(markets, list):
            result["markets"] = len(markets)
            result["market_ids"] = dict(Counter(
                str(x.get("marketId")) for x in markets if isinstance(x, dict)))
            result["market_names"] = sorted({
                str(x.get("marketName")) for x in markets
                if isinstance(x, dict) and x.get("marketName")
            })[:35]
            result["suspended_markets"] = sum(
                x.get("suspended") is True for x in markets if isinstance(x, dict))
            result["has_aces_ou"] = any(
                "ace" in str(x.get("marketName", "")).lower()
                and "over" in str(x.get("choices", "")).lower()
                for x in markets if isinstance(x, dict))
            result["bookmaker_named"] = bool(obj.get("bookmaker") or obj.get("providerName"))
            result["quote_timestamp_present"] = any(
                "timestamp" in str(k).lower() or "observed" in str(k).lower()
                for k in obj
            )
    elif name == "point_by_point":
        try:
            result["inventory"] = point_by_point_inventory(payload, event_id=event_id)
        except Exception as exc:
            result["inventory_error"] = type(exc).__name__
    elif name in ("odds_providers_sk_web", "odds_providers_sk_web_odds",
                  "odds_providers_gb_web"):
        providers = obj.get("providers") or obj.get("oddsProviders")
        if isinstance(providers, list):
            result["provider_count"] = len(providers)
            result["provider_ids"] = [
                str(p.get("id")) for p in providers[:20] if isinstance(p, dict)]
            result["provider_names"] = [
                str(p.get("name")) for p in providers[:20] if isinstance(p, dict)]
    return result


def run_probe(client: RapidTennisClient, *, event_id: int, max_requests: int) -> dict:
    if not 1 <= max_requests <= 30:
        raise ValueError("max_requests must be 1..30")
    client.request_limit = max_requests
    client.retry_attempts = 1  # deterministic bound, no surprise retries
    report = {
        "schema": 1, "source": "tennisapi1",
        "scope": "read_only_research_no_cdb_writes",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "target_event": event_id, "max_requests": max_requests,
        "observations": {}, "request_count": 0,
        "provider_quote_timestamp_verified": False,
        "eligible_for_cdb_import": False,
    }

    guard_halted = False

    def read(name: str, path: str, *, params: dict | None = None) -> Any:
        nonlocal guard_halted
        if guard_halted:
            report["observations"][name] = {"state": "shared_budget_guard_halted"}
            return {}
        if client.request_count >= max_requests:
            report["observations"][name] = {"state": "budget_cap"}
            return {}
        try:
            payload = client._get(path, params=params, enrichment=True)
            report["observations"][name] = summarize(name, payload, event_id=event_id)
            return payload
        except Exception as exc:
            reason = str(exc).lower()
            reason_code = (
                "missing_provider_header" if "header missing" in reason else
                "invalid_provider_header" if "invalid provider remaining header" in reason else
                "provider_reserve_reached" if "provider reserve" in reason else
                "shared_budget_exhausted" if "budget" in reason or "limit" in reason else
                "other"
            )
            if type(exc).__name__ in {
                    "RequestBudgetExceeded", "SharedBudgetExhausted",
                    "SharedBudgetUnavailable", "ConfigurationError"}:
                guard_halted = True
            report["observations"][name] = {
                "state": "error", "error_type": type(exc).__name__,
                "reason_code": reason_code,
                # Avoid copying provider response bodies or secrets into artifact.
            }
            return {}

    # Probe an existing documented event route FIRST to distinguish a general
    # account/header failure from an optional country-specific odds 204.
    detail = read("event_detail", f"/api/tennis/event/{event_id}")

    # Provider-country mapping must be checked *before* assuming 1 = any named book.
    read("odds_providers_sk_web", "/api/odds/providers/SK/web")
    read("odds_providers_sk_web_odds", "/api/odds/providers/SK/web-odds")
    read("odds_providers_gb_web", "/api/odds/providers/GB/web")

    # Calendar batching candidate versus today's production day route.
    read("monthly_categories", "/api/tennis/calendar/11/2026/categories",
         params={"days": "1,2,3,4,5"})
    read("monthly_calendar", "/api/tennis/calendar/11/2026")
    read("daily_categories", "/api/tennis/calendar/1/11/2026/categories")

    event = _obj(_obj(detail).get("event", detail))
    season_id = _nested_int(event, "season", "id")
    tournament_id = _nested_int(event, "tournament", "uniqueTournament", "id")
    if tournament_id is None:
        tournament_id = _nested_int(event, "tournament", "id")
    player_id = _nested_int(event, "homeTeam", "id")
    report["resolved_context"] = {
        "season_id": season_id, "tournament_id": tournament_id,
        "player_id": player_id, "event_id_matched": (
            str(event.get("id", event.get("eventId", ""))) == str(event_id))}

    read("event_odds", f"/api/tennis/event/{event_id}/odds/1/all")
    read("event_statistics", f"/api/tennis/event/{event_id}/statistics")
    read("point_by_point", f"/api/tennis/event/{event_id}/point-by-point")
    read("match_streak", f"/api/tennis/event/{event_id}/streak")
    read("graph_sequence", f"/api/tennis/event/{event_id}/graph/sequence")
    read("win_probability", f"/api/tennis/event/{event_id}/win-probability")

    if player_id is not None:
        read("previous_player_matches", f"/api/tennis/player/{player_id}/events/previous/0")
        read("legacy_last_player_matches", f"/api/tennis/player/{player_id}/events/last/0")
        read("singles_last_player_matches", f"/api/tennis/player/{player_id}/events/singles/last/0")
        read("player_rankings", f"/api/tennis/player/{player_id}/rankings")

    if season_id is not None:
        read("season_odds", f"/api/odds/season/{season_id}/provider/1/all")

    if tournament_id is not None:
        read("tournament_seasons", f"/api/tennis/tournament/{tournament_id}/seasons")
        if season_id is not None:
            prefix = f"/api/tennis/tournament/{tournament_id}/season/{season_id}"
            read("tournament_rounds", prefix + "/rounds")
            read("tournament_venues", prefix + "/venues")
            read("tournament_draw", prefix + "/cup-trees")

    report["request_count"] = client.request_count
    report["provider_header_remaining"] = client.rate_limit_remaining
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    report["counts"] = dict(Counter(
        x.get("state") for x in report["observations"].values()))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-id", type=int, default=14494928)
    parser.add_argument("--max-requests", type=int, default=24)
    parser.add_argument("--out", default=".cache/tbt/tennisapi-contract/live-probe.json")
    args = parser.parse_args()
    if args.event_id <= 0 or not 1 <= args.max_requests <= 30:
        parser.error("event-id must be positive, max-requests 1..30")
    if not os.getenv("BLINQ_SHARED_API_BUDGET_URL") or not os.getenv("BLINQ_SHARED_API_BUDGET_TOKEN"):
        parser.error("Shared RapidAPI budget credentials are required")
    client = RapidTennisClient()
    try:
        result = run_probe(client, event_id=args.event_id,
                           max_requests=args.max_requests)
    finally:
        client.close()
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    print(json.dumps({"probe_report": str(path), "request_count": result["request_count"],
                      "counts": result["counts"], "cdb_writes": 0}))


if __name__ == "__main__":
    main()
