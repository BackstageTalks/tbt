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
from tbt.providers.statistics import inventory_statistics_keys


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
    if name == "daily_match_winner_odds":
        # The provider returns an event-ID indexed odds map. Measure the value
        # structure from the EXISTING paid response, never a second request.
        # No raw quotes or per-event IDs leave this aggregate research report.
        price_map = obj.get("odds")
        if isinstance(price_map, dict):
            entries = list(price_map.items())
            valid_keys = [
                key for key, _ in entries
                if isinstance(key, str) and key.isascii() and key.isdecimal()
                and int(key) > 0
            ]
            value_kinds = Counter(type(value).__name__ for _, value in entries)
            with_markets = with_pair = with_event_echo = with_quote_clock = 0
            for key, value in entries:
                if not isinstance(value, dict):
                    continue
                with_markets += isinstance(value.get("markets"), list)
                with_pair += isinstance(value.get("home"), dict) and isinstance(
                    value.get("away"), dict)
                with_event_echo += str(value.get("eventId", value.get("event_id", ""))) == key
                with_quote_clock += any(
                    value.get(field) is not None
                    for field in ("quoteTimestamp", "quotedAt", "asOf", "observedAt")
                )
            result["daily_odds_value_profile"] = {
                "map_entries": len(entries),
                "valid_native_id_keys": len(valid_keys),
                "value_kinds": dict(sorted(value_kinds.items())),
                "entries_with_market_list": with_markets,
                "entries_with_home_away_objects": with_pair,
                "entries_with_matching_event_id_echo": with_event_echo,
                "entries_with_clock_like_field": with_quote_clock,
                "individual_event_market_replacement_authorized": False,
                "historical_pre_match_quote_time_verified": False,
                "cdb_import_authorized": False,
            }
        else:
            result["daily_odds_value_profile"] = {
                "recognized_id_map": False,
                "individual_event_market_replacement_authorized": False,
                "cdb_import_authorized": False,
            }
    if name in ("event_statistics", "historical_2016_match_statistics"):
        result["statistics_key_inventory"] = inventory_statistics_keys(payload)
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
    elif name.startswith("year_stats_") or name in ("team_year_stats_doc_example", "historical_2016_player_year_stats", "candidate_team_year_statistics"):
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
            if name == "candidate_team_year_statistics":
                surfaces = [str(group.get("groundType", "")).strip().lower()
                            for group in groups if isinstance(group, dict)]
                result["surface_groups_with_name"] = sum(bool(v) for v in surfaces)
                result["distinct_surfaces"] = len({v for v in surfaces if v})
                result["duplicate_surface_groups"] = (
                    len([v for v in surfaces if v])
                    - result["distinct_surfaces"])
                matches = [group.get("matches") for group in groups
                           if isinstance(group, dict)]
                result["groups_with_positive_matches"] = sum(
                    type(v) is int and v > 0 for v in matches)
                result["total_matches"] = sum(
                    v for v in matches if type(v) is int and v > 0)
                equations = (
                    ("totalServeAttempts", "firstServeTotal", "secondServeTotal"),
                    ("secondServeTotal", "secondServePointsTotal", "doubleFaults"),
                    ("firstServeTotal", "firstServePointsTotal",
                     "secondServePointsTotal", "doubleFaults"),
                )
                checked = failed = 0
                for group in groups:
                    if not isinstance(group, dict):
                        continue
                    for names in equations:
                        values = [group.get(key) for key in names]
                        if not all(type(v) is int and v >= 0 for v in values):
                            continue
                        checked += 1
                        if values[0] != sum(values[1:]):
                            failed += 1
                result["service_identity_checks"] = checked
                result["service_identity_violations"] = failed
            # Positive results are season aggregates, NOT match-level
            # candidate cells and NOT time-valid within their own season.
            result["point_in_time_match_eligibility"] = False
    elif name == "candidate_tournament_last_matches":
        events = obj.get("events")
        if isinstance(events, list):
            typed = [event for event in events if isinstance(event, dict)]
            ids = [str(event.get("id")) for event in typed
                   if type(event.get("id")) is int and event["id"] > 0]
            result["event_rows"] = len(events)
            result["valid_event_ids"] = len(ids)
            result["distinct_event_ids"] = len(set(ids))
            result["rows_with_two_players"] = sum(
                isinstance(event.get("homeTeam"), dict)
                and isinstance(event.get("awayTeam"), dict)
                for event in typed)
            result["rows_with_start_timestamp"] = sum(
                type(event.get("startTimestamp")) is int
                for event in typed)
        # A page cannot assert full-season completeness or CDB identity.
        result["completeness_verified"] = False
        if result["state"] != "no_content":
            if not isinstance(events, list):
                result["state"] = "unrecognized_shape"
            elif not events:
                result["state"] = "no_content"
            elif (len(ids) != len(events) or len(set(ids)) != len(ids)
                  or result["rows_with_two_players"] != len(events)
                  or result["rows_with_start_timestamp"] != len(events)):
                result["state"] = "invalid_shape"
    elif name == "candidate_player_singles_results":
        events = obj.get("events")
        if result["state"] != "no_content":
            if not isinstance(events, list):
                result["state"] = "unrecognized_shape"
            elif not events:
                result["state"] = "no_content"
            elif not all(
                isinstance(event, dict)
                and type(event.get("id")) is int and event["id"] > 0
                and isinstance(event.get("homeTeam"), dict)
                and isinstance(event.get("awayTeam"), dict)
                and type(event.get("startTimestamp")) is int
                and event["startTimestamp"] > 0
                for event in events
            ):
                result["state"] = "invalid_shape"
            elif len({event["id"] for event in events}) != len(events):
                result["state"] = "invalid_shape"
            else:
                result["event_rows"] = len(events)
                result["unique_event_ids"] = len(events)
                result["dated_event_rows"] = len(events)
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
    if name == "candidate_team_year_statistics" and result["state"] != "no_content":
        stats = obj.get("statistics")
        if not isinstance(stats, list):
            result["state"] = "unrecognized_shape"
        elif not stats:
            result["state"] = "no_content"
        elif not all(isinstance(group, dict) for group in stats):
            result["state"] = "invalid_shape"
        elif (result.get("groups_with_positive_matches") != len(stats)
              or result.get("surface_groups_with_name") != len(stats)
              or result.get("duplicate_surface_groups", 0) > 0
              or result.get("statistic_bound_violations", 0) > 0
              or result.get("service_identity_violations", 0) > 0
              or not any(
                  result.get("non_null_fields", {}).get(field, 0) > 0
                  for field in (
                      "firstServePointsTotal", "secondServePointsTotal",
                      "breakPointsTotal", "opponentBreakPointsTotal"
                  ))):
            result["state"] = "invalid_statistics"
    return result


def run_probe(client: RapidTennisClient, *, event_id: int, max_requests: int,
              phase: str = "full", case: str | None = None) -> dict:
    if not 1 <= max_requests <= 30:
        raise ValueError("max_requests must be 1..30")
    if phase not in {"full", "metadata", "odds", "doubles", "quality",
                     "historical", "identity", "archive_2016", "candidates",
                     "discovery", "bulk", "bulk_odds_shape"}:
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

    if phase == "bulk_odds_shape":
        # Focused two-call structural contract: one identity/date witness and
        # one full-day bulk odds map, never fourteen overlapping route probes.
        if case is not None or max_requests != 2:
            raise ValueError("Bulk odds shape requires exactly 2 calls and no case")
        detail = read("bulk_source_event_detail",
                      f"/api/tennis/event/{event_id}")
        event = _obj(_obj(detail).get("event", detail))
        matched = str(event.get("id", event.get("eventId", ""))) == str(event_id)
        home = _nested_int(event, "homeTeam", "id")
        away = _nested_int(event, "awayTeam", "id")
        stamp = event.get("startTimestamp")
        try:
            if type(stamp) is not int or stamp <= 0:
                raise ValueError("Invalid event timestamp")
            day = datetime.fromtimestamp(stamp, timezone.utc).date()
        except (ValueError, OverflowError, OSError):
            day = None
        if not (matched and home and away and home != away and day):
            report["bulk_odds_shape_state"] = "invalid_source_witness"
            return finish()
        report["bulk_source_event_id_matched"] = True
        period = f"{day.day}/{day.month}/{day.year}"
        read("daily_match_winner_odds",
             f"/api/tennis/events/odds/{period}")
        profile = report["observations"]["daily_match_winner_odds"].get(
            "daily_odds_value_profile", {})
        report["bulk_odds_shape_state"] = (
            "profiled" if "map_entries" in profile else "unrecognized_shape")
        report["cdb_writes"] = 0
        report["model_changes"] = 0
        return finish()

    if phase == "bulk":
        # One guarded source witness, followed by independent documented route
        # samples. There are 14 optional routes: <=15 provider requests total.
        # Never pretend public example tournament params match the source event.
        if case is not None or not 2 <= max_requests <= 16:
            raise ValueError("Bulk probe requires no case and 2..16 calls")
        detail = read("bulk_source_event_detail",
                      f"/api/tennis/event/{event_id}")
        event = _obj(_obj(detail).get("event", detail))
        matched = str(event.get("id", event.get("eventId", ""))) == str(event_id)
        home = _nested_int(event, "homeTeam", "id")
        away = _nested_int(event, "awayTeam", "id")
        tournament = (_nested_int(event, "tournament", "uniqueTournament", "id")
                      or _nested_int(event, "tournament", "id"))
        season = _nested_int(event, "season", "id")
        stamp = event.get("startTimestamp")
        try:
            if type(stamp) is not int or stamp <= 0:
                raise ValueError("Invalid native event timestamp")
            day = datetime.fromtimestamp(stamp, timezone.utc).date()
        except (ValueError, OverflowError, OSError):
            day = None
        report["bulk_source_event_id_matched"] = bool(
            matched and home and away and home != away and tournament and
            season and day
        )
        report["bulk_context"] = {
            "source_event_id_matched": bool(matched),
            "source_native_players_confirmed": bool(home and away and home != away),
            "source_native_tournament_present": bool(tournament),
            "source_native_season_present": bool(season),
            "source_native_day_present": bool(day),
            "identity_validated_for_cdb_import": False,
            "provider_aggregate_response_complete": False,
        }
        if not report["bulk_source_event_id_matched"]:
            report["bulk_state"] = "invalid_source_witness"
            return finish()

        t = f"/api/tennis/tournament/{tournament}"
        y = f"{t}/season/{season}"
        period = f"{day.day}/{day.month}/{day.year}"
        month = f"{day.month:02d}"  # Provider documentation requires zero padding.
        routes = [
            ("tournament_last_matches", f"{y}/events/last/0", "source_native"),
            ("tournament_matches_by_date", f"{t}/schedules/{period}", "source_native"),
            ("player_month_matches",
             f"/api/tennis/player/{home}/events/{month}/{day.year}", "source_native"),
            ("team_month_matches",
             f"/api/tennis/team/{home}/events/{month}/{day.year}", "source_native"),
            ("featured_tennis_odds",
             "/api/tennis/events/odds/featured/1", "independent_current_list"),
            ("match_winning_odds",
             f"/api/tennis/event/{event_id}/provider/1/winning-odds", "source_native"),
            ("match_betting_odds",
             f"/api/tennis/event/{event_id}/odds", "source_native"),
            ("newly_added_events", "/api/event/newly-added", "independent_current_list"),
            ("scheduled_tournaments_by_date",
             f"/api/tennis/scheduled-tournaments/{period}/page/1", "source_native"),
            ("monthly_calendar",
             f"/api/tennis/calendar/{day.month}/{day.year}", "source_native"),
            ("daily_match_winner_odds",
             f"/api/tennis/events/odds/{period}", "source_native"),
            ("tournament_rounds", f"{y}/rounds", "source_native"),
            ("tournament_draw", f"{y}/cup-trees", "source_native"),
            ("tournament_round_documented_example",
             "/api/tennis/tournament/2363/season/48186/events/round/32/slug/round-of-64",
             "independent_documented_example_2023"),
        ]
        for name, path, provenance in routes:
            payload = read(name, path)
            observed = report["observations"][name]
            observed["query_provenance"] = provenance
            observed["eligible_for_cdb_import"] = False
            observed["point_in_time_odds_verified"] = False
            observed["source_coverage_complete"] = False
            body = _obj(payload)
            candidate = None
            for field in ("events", "matches", "tournaments",
                          "dailyUniqueTournaments", "markets", "odds"):
                if isinstance(body.get(field), list):
                    candidate = body[field]
                    observed["source_list_field"] = field
                    break
            if candidate is None and isinstance(payload, list):
                candidate = payload
                observed["source_list_field"] = "_root"
            if candidate is not None:
                observed["source_rows"] = len(candidate)
                event_ids = [row.get("id") for row in candidate
                             if isinstance(row, dict)
                             and type(row.get("id")) is int and row["id"] > 0]
                observed["unique_native_event_ids"] = len(set(event_ids))
                observed["duplicate_native_event_ids"] = len(event_ids) - len(set(event_ids))
                observed["source_witness_event_found"] = event_id in event_ids
                observed["source_witness_event_id_match_only"] = (
                    bool(provenance == "source_native" and event_id in event_ids))
                # Event ID overlap alone never proves canonical CDB identity.
        report["bulk_state"] = "tested"
        report["bulk_endpoint_observations"] = len(routes)
        report["bulk_endpoints_with_source_rows"] = sum(
            (report["observations"][name].get("source_rows", 0) or 0) > 0
            for name, _, _ in routes)
        report["cdb_writes"] = 0
        report["model_changes"] = 0
        return finish()

    if phase == "archive_2016":
        # Historical event selection is SOURCE-NATIVE and deterministic, not
        # canonical CDB identity matching. No backdating or writes.
        if case is not None:
            raise ValueError("Archive phase does not accept case")
        # The retired flat /api/tennis/events/{date} route returns 204 even
        # when category-scoped historical events are available. Resolve the
        # provider's documented category calendar first; do not claim an empty
        # 2016 archive from an unavailable discovery response.
        from tbt.errors import ProviderError
        categories_response = read(
            "archived_categories", "/api/tennis/calendar/10/7/2016/categories")
        try:
            categories = RapidTennisClient._response_rows(
                categories_response, "categories")
        except ProviderError:
            report["historical_sample_policy"] = "category_calendar_unavailable"
            return finish()
        report["archived_category_count"] = len(categories)
        # The provider may group old Slam fixtures under ATP/WTA rather than
        # a synthetic -100 Grand Slam category. Scan the exact categories
        # returned by this historical calendar; never invent category IDs.
        category_ids = [RapidTennisClient._category_id(row)
                        for row in categories]
        if (not category_ids
                or any(value is None for value in category_ids)
                or len(category_ids) != len(set(category_ids))):
            report["historical_sample_policy"] = "category_identity_ambiguous"
            return finish()
        report["historical_source_category_ids"] = category_ids
        events = []
        unavailable_categories = []
        for category_id in category_ids:
            day = read(
                f"archived_category_events_{category_id}",
                f"/api/tennis/category/{category_id}/events/10/7/2016")
            try:
                rows = RapidTennisClient._response_rows(day, "events")
            except ProviderError:
                unavailable_categories.append(category_id)
                continue
            events.extend(rows)
        report["archived_categories_unavailable"] = unavailable_categories
        report["archived_category_scan_complete"] = not unavailable_categories
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
                    == "finished"
                and RapidTennisClient._is_singles_event(e))
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

    if phase == "discovery":
        # Two guarded reads maximum: native event witness + one discovery
        # endpoint. A no-content result does not justify skipping CDB dates.
        cases = {
            "tournament_venue_events",
            "tournament_events_on_date",
            "tournaments_by_category",
            "player_recent_tournaments",
            "calendar_days_with_events",
        }
        if case not in cases:
            raise ValueError("discovery phase requires a preapproved case")
        if max_requests < 2:
            raise ValueError("discovery requires at least two requests")
        detail = read("discovery_event_detail",
                      f"/api/tennis/event/{event_id}")
        event = _obj(_obj(detail).get("event", detail))
        matched = str(event.get("id", event.get("eventId", ""))) == str(event_id)
        tournament = (_nested_int(event, "tournament", "uniqueTournament", "id")
                      or _nested_int(event, "tournament", "id"))
        season = _nested_int(event, "season", "id")
        player = _nested_int(event, "homeTeam", "id")
        venue = _nested_int(event, "venue", "id")
        category = (_nested_int(event, "tournament", "category", "id")
                    or _nested_int(event, "tournament", "uniqueTournament",
                                   "category", "id"))
        stamp = event.get("startTimestamp")
        year = None
        day = None
        if type(stamp) is int and stamp > 0:
            try:
                point = datetime.fromtimestamp(stamp, tz=timezone.utc)
                year, day = point.year, point.date().isoformat()
            except (ValueError, OverflowError, OSError):
                pass
        report["discovery_context"] = {
            "source_event_id_matched": matched,
            "has_native_tournament": bool(tournament),
            "has_native_season": bool(season),
            "has_native_player": bool(player),
            "has_native_venue": bool(venue),
            "has_native_category": bool(category),
            "has_date": bool(day),
            "identity_validated_for_import": False,
            "cdb_overlap_verified": False,
        }
        if not matched:
            report["discovery_state"] = "invalid_source_event"
            return finish()
        route = None
        if case == "tournament_venue_events" and tournament and season and venue:
            route = (f"/api/tennis/tournament/{tournament}/season/{season}"
                     f"/venue/{venue}/events/all/0")
        elif case == "tournament_events_on_date" and tournament and day:
            route = f"/api/tennis/tournament/{tournament}/scheduled-events/{day}"
        elif case == "tournaments_by_category" and category:
            route = f"/api/tennis/tournament/all/category/{category}"
        elif case == "player_recent_tournaments" and player:
            route = f"/api/tennis/player/{player}/tournaments/last"
        elif case == "calendar_days_with_events" and season and year:
            route = f"/api/calendar/season/{season}/{year}/days-with-events"
        if route is None:
            report["discovery_state"] = "missing_native_context"
            return finish()
        payload = read("discovery_" + case, route)
        observation = report["observations"]["discovery_" + case]
        # Report counts without treating a metadata hit as a canonical row.
        obj = _obj(payload)
        for collection in ("events", "tournaments", "uniqueTournaments", "days"):
            rows = obj.get(collection)
            if isinstance(rows, list):
                observation["source_rows"] = len(rows)
                break
        observation["cdb_overlap_verified"] = False
        observation["eligible_for_cdb_import"] = False
        observation["completeness_verified"] = False
        report["discovery_state"] = "endpoint_" + str(observation["state"])
        return finish()

    if phase == "candidates":
        # Exactly one source-native event witness and one optional research route.
        # No match CDB writes or same-season pre-match features are authorized.
        allowed_cases = {
            "team_year_statistics", "tournament_last_matches",
            "player_singles_results",
        }
        if case not in allowed_cases:
            raise ValueError("candidates phase requires a preapproved case")
        detail = read("candidate_event_detail", f"/api/tennis/event/{event_id}")
        event = _obj(_obj(detail).get("event", detail))
        matches = str(event.get("id", event.get("eventId", ""))) == str(event_id)
        player_id = _nested_int(event, "homeTeam", "id")
        tournament_id = (
            _nested_int(event, "tournament", "uniqueTournament", "id")
            or _nested_int(event, "tournament", "id"))
        season_id = _nested_int(event, "season", "id")
        report["candidate_context"] = {
            "source_event_id_matched": matches,
            "source_home_team_id": player_id,
            "source_tournament_id": tournament_id,
            "source_season_id": season_id,
            "identity_validated_for_import": False,
            "point_in_time_verified": False,
        }
        if not matches:
            report["candidate_state"] = "unavailable_or_mismatched_event"
            return finish()

        if case == "team_year_statistics":
            stamp = event.get("startTimestamp")
            if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp <= 0:
                report["candidate_state"] = "missing_start_timestamp"
                return finish()
            year = datetime.fromtimestamp(stamp, tz=timezone.utc).year
            if not player_id or year > datetime.now(timezone.utc).year:
                report["candidate_state"] = "invalid_player_or_year"
                return finish()
            route = f"/api/tennis/team/{player_id}/year-statistics/{year}"
            report["candidate_context"]["source_year"] = year
        elif case == "tournament_last_matches":
            if not tournament_id or not season_id:
                report["candidate_state"] = "missing_tournament_or_season"
                return finish()
            route = (
                f"/api/tennis/tournament/{tournament_id}"
                f"/season/{season_id}/events/last/0")
        else:
            if not player_id:
                report["candidate_state"] = "missing_player"
                return finish()
            route = f"/api/tennis/player/{player_id}/events/singles/last/0"

        payload = read("candidate_" + case, route)
        observed = report["observations"]["candidate_" + case]
        if case == "player_singles_results" and observed["state"] == "available":
            # Source-native counts only. Never expose raw opponent IDs, accept
            # mismatched rows or infer canonical CDB identity from a 200 reply.
            events = _obj(payload).get("events")
            matched = missing = identical = unrelated = 0
            for item in events if isinstance(events, list) else []:
                home_id = _nested_int(item, "homeTeam", "id")
                away_id = _nested_int(item, "awayTeam", "id")
                if home_id is None or away_id is None:
                    missing += 1
                elif home_id == away_id:
                    identical += 1
                elif player_id not in (home_id, away_id):
                    unrelated += 1
                else:
                    matched += 1
            observed["source_player_match_rows"] = matched
            observed["missing_participant_identity_rows"] = missing
            observed["identical_participant_identity_rows"] = identical
            observed["unrelated_participant_rows"] = unrelated
            if (not isinstance(events, list)
                    or matched != len(events)
                    or missing or identical or unrelated):
                observed["state"] = "invalid_identity"
        report["candidate_state"] = "endpoint_" + str(observed["state"])
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

    # Public provider-native identity witness for a ONE-call focused archive
    # audit. No names/IDs from this report are approved for CDB writes without
    # independent canonical crosswalk, score/winner, round and date validation.
    tournament = _obj(event.get("tournament"))
    category = _obj(tournament.get("category"))
    unique = _obj(tournament.get("uniqueTournament"))
    home = _obj(event.get("homeTeam"))
    away = _obj(event.get("awayTeam"))
    status = _obj(event.get("status"))
    round_info = _obj(event.get("roundInfo"))
    source_category_id = _nested_int(tournament, "category", "id")
    report["source_event_identity"] = {
        "event_id": str(event.get("id", event.get("eventId", ""))),
        "event_id_matches_request": (
            str(event.get("id", event.get("eventId", ""))) == str(event_id)),
        "home_id": _nested_int(event, "homeTeam", "id"),
        "away_id": _nested_int(event, "awayTeam", "id"),
        "home_name": str(home.get("name") or ""),
        "away_name": str(away.get("name") or ""),
        "status": str(status.get("type") or ""),
        "start_timestamp": event.get("startTimestamp"),
        "tournament_name": str(tournament.get("name") or unique.get("name") or ""),
        "tournament_id": _nested_int(event, "tournament", "id"),
        "unique_tournament_id": _nested_int(event, "tournament", "uniqueTournament", "id"),
        "category_id": source_category_id,
        "category_name": str(category.get("name") or ""),
        "round": str(round_info.get("name") or round_info.get("round") or ""),
        "winner_code": event.get("winnerCode"),
        "singles_structure": RapidTennisClient._is_singles_event(event),
        "derived_tour": RapidTennisClient._event_tour(
            event, source_category_id, str(category.get("name") or "")),
        "identity_validated_for_cdb": False,
    }

    statistics_payload = read("event_statistics", f"/api/tennis/event/{event_id}/statistics")
    # The exact provider event witness binds both player IDs to whole-match
    # statistics. Never derive a pick's ACES result from its match winner.
    if (report["source_event_identity"]["event_id_matches_request"]
            and report["source_event_identity"]["singles_structure"]
            and report["source_event_identity"]["home_id"]
            and report["source_event_identity"]["away_id"]
            and report["source_event_identity"]["home_id"] != report["source_event_identity"]["away_id"]
            and report["source_event_identity"]["status"] == "finished"
            and isinstance(statistics_payload, dict)
            and statistics_payload.get("statistics")):
        from tbt.providers.statistics import parse_statistics
        verified = parse_statistics(statistics_payload, home_is_player1=True)
        home_aces, away_aces = verified.get("p1_aces"), verified.get("p2_aces")
        if (home_aces is not None and away_aces is not None
                and float(home_aces).is_integer() and float(away_aces).is_integer()):
            report["source_native_aces_evidence"] = {
                "event_id": str(event_id),
                "home_id": report["source_event_identity"]["home_id"],
                "away_id": report["source_event_identity"]["away_id"],
                "home_aces": int(home_aces), "away_aces": int(away_aces),
                "statistics_payload_sha256": report["observations"]["event_statistics"]["payload_sha256"],
                "provider_checked_utc": datetime.now(timezone.utc).isoformat(),
            }
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
                                            "archive_2016", "candidates",
                                            "discovery", "bulk", "bulk_odds_shape"],
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
