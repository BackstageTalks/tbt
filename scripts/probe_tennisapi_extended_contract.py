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
    # Keep only structural evidence from nested provider collections; never
    # export full odds, identities, raw event records or undeclared metrics.
    result["collections"] = {}
    for field, value in list(obj.items())[:30]:
        if isinstance(value, list):
            first = next((row for row in value if isinstance(row, dict)), None)
            result["collections"][str(field)] = {
                "kind": "list", "count": len(value),
                "sample_keys": sorted(map(str, first))[:22] if first else [],
            }
        elif isinstance(value, dict):
            result["collections"][str(field)] = {
                "kind": "dict", "keys": sorted(map(str, value))[:22],
                "count": len(value),
            }
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
    elif name.startswith("year_stats_") or name in ("team_year_stats_doc_example", "historical_2016_player_year_stats"):
        groups = obj.get("statistics")
        if isinstance(groups, list):
            known = (
                "aces", "doubleFaults", "firstServePointsScored",
                "firstServePointsTotal", "secondServePointsScored",
                "secondServePointsTotal", "breakPointsScored",
                "breakPointsTotal", "opponentBreakPointsScored",
                "opponentBreakPointsTotal", "matches",
            )
            result["season_stat_groups"] = len(groups)
            result["non_null_fields"] = {
                key: sum(
                    isinstance(group, dict) and group.get(key) is not None
                    for group in groups
                ) for key in known
            }
            pairs = (
                ("firstServePointsScored", "firstServePointsTotal"),
                ("secondServePointsScored", "secondServePointsTotal"),
                ("breakPointsScored", "breakPointsTotal"),
                ("opponentBreakPointsScored", "opponentBreakPointsTotal"),
            )
            observed = 0
            violations = 0
            for group in groups:
                if not isinstance(group, dict):
                    continue
                for scored, total in pairs:
                    a, b = group.get(scored), group.get(total)
                    if (isinstance(a, (int, float)) and not isinstance(a, bool)
                            and isinstance(b, (int, float)) and not isinstance(b, bool)):
                        observed += 1
                        if a < 0 or b < 0 or a > b:
                            violations += 1
            result["statistic_pairs_compared"] = observed
            result["statistic_bound_violations"] = violations
            # Positive results are season aggregates, NOT match-level
            # candidate cells and NOT time-valid within their own season.
            result["point_in_time_match_eligibility"] = False
    elif name in ("point_by_point", "historical_2016_point_by_point"):
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


def run_probe(client: RapidTennisClient, *, event_id: int, max_requests: int,
              phase: str = "full", case: str | None = None) -> dict:
    if not 1 <= max_requests <= 30:
        raise ValueError("max_requests must be 1..30")
    if phase not in {"full", "metadata", "odds", "doubles", "quality",
                     "historical", "identity", "archive_2016"}:
        raise ValueError("Unknown preapproved TennisApi probe phase")
    if case is not None and phase == "full":
        raise ValueError("Focused case requires a named phase")
    client.request_limit = max_requests
    client.retry_attempts = 1  # deterministic bound, no surprise retries
    report = {
        "schema": 1, "source": "tennisapi1",
        "scope": "read_only_research_no_cdb_writes",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "target_event": event_id, "max_requests": max_requests,
        "phase": phase, "case": case or "all",
        "observations": {}, "request_count": 0,
        "provider_quote_timestamp_verified": False,
        "eligible_for_cdb_import": False,
    }

    guard_halted = False
    last_http: dict[str, object] = {}

    def observe_response(response: Any) -> None:
        # Passive HTTP metadata only; never read, log or persist credentials or
        # raw response bodies. The existing provider header guard stays intact.
        last_http["http_status"] = int(response.status_code)
        last_http["quota_header_present"] = (
            "x-ratelimit-requests-remaining" in response.headers)

    http = getattr(client, "client", None)
    if http is not None and isinstance(getattr(http, "event_hooks", None), dict):
        http.event_hooks.setdefault("response", []).append(observe_response)

    def read(name: str, path: str, *, params: dict | None = None,
             source_event_id: int | None = None) -> Any:
        nonlocal guard_halted
        if guard_halted:
            report["observations"][name] = {"state": "shared_budget_guard_halted"}
            return {}
        if client.request_count >= max_requests:
            report["observations"][name] = {"state": "budget_cap"}
            return {}
        try:
            last_http.clear()
            payload = client._get(path, params=params, enrichment=True)
            report["observations"][name] = {
                **summarize(name, payload, event_id=source_event_id or event_id),
                **last_http}
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
                "reason_code": reason_code, **last_http,
                # Avoid copying provider response bodies or secrets into artifact.
            }
            return {}

    def finish() -> dict:
        report["request_count"] = client.request_count
        report["provider_header_remaining"] = client.rate_limit_remaining
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        report["counts"] = dict(Counter(
            x.get("state") for x in report["observations"].values()))
        return report

    if phase == "archive_2016":
        # Historical event selection is SOURCE-NATIVE and deterministic, not
        # canonical CDB identity matching. No backdating or writes.
        if case is not None:
            raise ValueError("Archive phase does not accept case")
        day = read("archived_day_events", "/api/tennis/events/10/7/2016")
        raw_events = _obj(day).get("events")
        events = raw_events if isinstance(raw_events, list) else []
        report["archived_event_count"] = len(events)
        valid = [
            e for e in events
            if (isinstance(e, dict)
                and _nested_int(e, "id")
                and _nested_int(e, "homeTeam", "id")
                and _nested_int(e, "awayTeam", "id")
                and _nested_int(e, "homeTeam", "id")
                    != _nested_int(e, "awayTeam", "id")
                and str(_obj(e.get("status")).get("type", "")).lower()
                    == "finished")
        ]
        target = [
            e for e in valid
            if "wimbledon" in json.dumps(
                _obj(e.get("tournament")), ensure_ascii=False).lower()
        ]
        choices = sorted(target or valid, key=lambda e: int(e["id"]))
        report["historical_sample_policy"] = (
            "wimbledon_finished" if target else
            "other_finished" if valid else "no_valid_completed_event")
        report["historical_candidate_count"] = len(target or valid)
        if choices:
            chosen = choices[0]
            match_id = int(chosen["id"])
            home_id = _nested_int(chosen, "homeTeam", "id")
            report["historical_sample_event_id"] = match_id
            report["historical_source_home_id"] = home_id
            report["identity_validated_for_import"] = False
            read("historical_2016_match_statistics",
                 f"/api/tennis/event/{match_id}/statistics")
            read("historical_2016_point_by_point",
                 f"/api/tennis/event/{match_id}/point-by-point",
                 source_event_id=match_id)
            read("historical_2016_player_year_stats",
                 f"/api/tennis/team/{home_id}/year-statistics/2016")
        return finish()

    if phase != "full":
        # Proven event context: event 14494928 / season 67287 /
        # tournament 2449 / player 206570. Team IDs are DOCUMENTATION
        # examples only, never identity-verified CDB matches.
        routes = {
            "metadata": [
                ("tournament_rounds", "/api/tennis/tournament/2449/season/67287/rounds"),
                ("tournament_seasons", "/api/tennis/tournament/2449/seasons"),
                ("tournament_draw", "/api/tennis/tournament/2449/season/67287/cup-trees"),
                ("tournament_venues", "/api/tennis/tournament/2449/season/67287/venues"),
                ("player_rankings", "/api/tennis/player/206570/rankings"),
                ("singles_last_player_matches", "/api/tennis/player/206570/events/singles/last/0"),
            ],
            "odds": [
                ("event_odds", f"/api/tennis/event/{event_id}/odds/1/all"),
                ("season_odds", "/api/odds/season/67287/provider/1/all"),
                ("odds_providers_sk_web_odds", "/api/odds/providers/SK/web-odds"),
                ("odds_providers_gb_web", "/api/odds/providers/GB/web"),
                ("odds_providers_sk_web", "/api/odds/providers/SK/web"),
            ],
            "doubles": [
                ("team_roster_doc_example", "/api/tennis/team/39234/players"),
                ("team_year_stats_doc_example", "/api/tennis/team/69208/year-statistics/2025"),
            ],
            "quality": [
                ("match_streak", f"/api/tennis/event/{event_id}/streak"),
                ("graph_sequence", f"/api/tennis/event/{event_id}/graph/sequence"),
                ("win_probability", f"/api/tennis/event/{event_id}/win-probability"),
            ],
            "identity": [
                ("player_details_doc_example", "/api/tennis/player/69208"),
                ("team_details_doc_example", "/api/tennis/team/69208"),
            ],
            "historical": [
                ("year_stats_2024", "/api/tennis/team/69208/year-statistics/2024"),
                ("year_stats_2022", "/api/tennis/team/69208/year-statistics/2022"),
                ("year_stats_2020", "/api/tennis/team/69208/year-statistics/2020"),
                ("year_stats_2016", "/api/tennis/team/69208/year-statistics/2016"),
                ("year_stats_2026", "/api/tennis/team/69208/year-statistics/2026"),
            ],
        }
        report["context_origin"] = "verified_provider_event_or_documentation"
        report["identity_validated_for_import"] = False
        names = {name for name, _ in routes[phase]}
        if case is not None and case not in names:
            raise ValueError("Focused case not in the preapproved route allowlist")
        for name, route in routes[phase]:
            if case is None or name == case:
                read(name, route)
        return finish()

    # Known event and post-match CDB fields first. Country odds provider
    # lookup may legitimately return 204 without the required quota header.
    # Keep it last so a single missing header cannot mask core source coverage.
    detail = read("event_detail", f"/api/tennis/event/{event_id}")
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

    read("event_statistics", f"/api/tennis/event/{event_id}/statistics")
    read("point_by_point", f"/api/tennis/event/{event_id}/point-by-point")
    read("monthly_categories", "/api/tennis/calendar/11/2026/categories",
         params={"days": "1,2,3,4,5"})
    read("monthly_calendar", "/api/tennis/calendar/11/2026")
    read("daily_categories", "/api/tennis/calendar/1/11/2026/categories")

    if player_id is not None:
        read("previous_player_matches", f"/api/tennis/player/{player_id}/events/previous/0")
        read("legacy_last_player_matches", f"/api/tennis/player/{player_id}/events/last/0")
        read("singles_last_player_matches", f"/api/tennis/player/{player_id}/events/singles/last/0")
        read("player_rankings", f"/api/tennis/player/{player_id}/rankings")

    if season_id is not None:
        read("season_odds", f"/api/odds/season/{season_id}/provider/1/all")

    read("event_odds", f"/api/tennis/event/{event_id}/odds/1/all")
    if tournament_id is not None:
        read("tournament_seasons", f"/api/tennis/tournament/{tournament_id}/seasons")
        if season_id is not None:
            prefix = f"/api/tennis/tournament/{tournament_id}/season/{season_id}"
            read("tournament_rounds", prefix + "/rounds")
            read("tournament_venues", prefix + "/venues")
            read("tournament_draw", prefix + "/cup-trees")

    read("match_streak", f"/api/tennis/event/{event_id}/streak")
    read("graph_sequence", f"/api/tennis/event/{event_id}/graph/sequence")
    read("win_probability", f"/api/tennis/event/{event_id}/win-probability")

    # Experimental country odds lookup LAST: no quota-header bypass.
    read("odds_providers_sk_web", "/api/odds/providers/SK/web")
    read("odds_providers_sk_web_odds", "/api/odds/providers/SK/web-odds")
    read("odds_providers_gb_web", "/api/odds/providers/GB/web")

    return finish()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-id", type=int, default=14494928)
    parser.add_argument("--max-requests", type=int, default=24)
    parser.add_argument("--phase", choices=["full", "metadata", "odds", "doubles",
                                            "quality", "historical", "identity",
                                            "archive_2016"],
                        default="full")
    parser.add_argument("--case", default=None)
    parser.add_argument("--out", default=".cache/tbt/tennisapi-contract/live-probe.json")
    args = parser.parse_args()
    if args.event_id <= 0 or not 1 <= args.max_requests <= 30:
        parser.error("event-id must be positive, max-requests 1..30")
    if not os.getenv("BLINQ_SHARED_API_BUDGET_URL") or not os.getenv("BLINQ_SHARED_API_BUDGET_TOKEN"):
        parser.error("Shared RapidAPI budget credentials are required")
    client = RapidTennisClient()
    try:
        result = run_probe(client, event_id=args.event_id,
                           max_requests=args.max_requests, phase=args.phase,
                           case=args.case)
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
