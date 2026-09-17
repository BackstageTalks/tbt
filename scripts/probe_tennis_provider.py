#!/usr/bin/env python3
"""Read-only TennisApi capability probe for BlinQ.

Purpose:
- verify whether raw daily discovery exposes doubles / mixed doubles;
- capture pair/team/member identity shapes without routing them into singles history;
- inspect provider-1 odds market names for Match Winner, Aces, Sets, Games,
  First Set and Tie Break markets;
- inspect a very small number of finished-event statistics payloads.

The script never writes canonical history, predictions, accounts, or admin data.
It only writes a local JSON/Markdown diagnostic report.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tbt.errors import ProviderError
from tbt.providers.budget import RequestBudgetExceeded
from tbt.providers.rapidapi import RapidTennisClient
from tbt.services.market_selection import _outcome_text, _price, _walk_market_rows
from tbt.utils import first_present


def _event_id(row: dict[str, Any]) -> str:
    value = first_present(row, "id", "eventId", "event_id")
    return str(value or "").strip()


def _event_name(row: dict[str, Any]) -> str:
    tournament = row.get("tournament") if isinstance(row.get("tournament"), dict) else {}
    unique = tournament.get("uniqueTournament") if isinstance(tournament.get("uniqueTournament"), dict) else {}
    return str(
        first_present(unique, "name", "slug")
        or first_present(tournament, "name", "slug")
        or first_present(row, "name", "slug")
        or ""
    ).strip()


def _status(row: dict[str, Any]) -> str:
    status = row.get("status")
    if isinstance(status, dict):
        return str(first_present(status, "type", "description", "name") or "").strip().lower()
    return str(status or "").strip().lower()


def _scheduled_at(row: dict[str, Any]) -> str:
    for key in ("startTimestamp", "start_time", "scheduled_at", "timestamp"):
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if number > 10_000_000_000:
            number /= 1000.0
        try:
            return datetime.fromtimestamp(number, timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            return str(value)
    return ""


def _side(row: dict[str, Any], key: str) -> dict[str, Any]:
    side = row.get(key)
    if not isinstance(side, dict):
        return {}
    members = first_present(side, "players", "members", "subTeams")
    member_rows = members if isinstance(members, list) else []
    normalized_members = []
    for member in member_rows[:6]:
        if not isinstance(member, dict):
            continue
        normalized_members.append({
            "id": str(first_present(member, "id", "playerId", "teamId") or ""),
            "name": str(first_present(member, "name", "shortName", "slug") or ""),
            "keys": sorted(member.keys()),
        })
    return {
        "id": str(first_present(side, "id", "teamId", "playerId") or ""),
        "name": str(first_present(side, "name", "shortName", "slug") or ""),
        "member_count": len(member_rows),
        "members": normalized_members,
        "keys": sorted(side.keys()),
    }


def _classify(client: RapidTennisClient, row: dict[str, Any]) -> str:
    text = client._event_text(row)
    if "mixed double" in text or "mixed doubles" in text:
        return "mixed_doubles"
    if not client._is_singles_event(row):
        return "doubles"
    return "singles"


def _event_summary(client: RapidTennisClient, row: dict[str, Any], category_id: int, category_name: str) -> dict[str, Any]:
    kind = _classify(client, row)
    return {
        "event_id": _event_id(row),
        "kind": kind,
        "tour": client._event_tour(row, category_id, category_name),
        "category_id": category_id,
        "category_name": category_name,
        "tournament": _event_name(row),
        "scheduled_at": _scheduled_at(row),
        "status": _status(row),
        "home": _side(row, "homeTeam"),
        "away": _side(row, "awayTeam"),
        "event_keys": sorted(row.keys()),
    }


def _line_fields(row: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key in (
        "line", "handicap", "total", "points", "value", "choiceName", "choice_name",
        "outcomeName", "outcome_name", "label", "name", "selection", "specifier",
    ):
        value = row.get(key)
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            result[key] = value
    return result


def _market_bucket(name: str, outcome: str) -> str:
    text = f"{name} {outcome}".casefold().replace("_", " ")
    if "ace" in text:
        return "aces"
    if "double fault" in text or "doublefault" in text:
        return "double_faults"
    if "first set" in text or "1st set" in text:
        return "first_set"
    if "tie break" in text or "tiebreak" in text:
        return "tie_break"
    if "game" in text or "total" in text and "set" not in text:
        return "games_or_totals"
    if "set" in text:
        return "sets"
    if any(token in text for token in ("match winner", "full time", "moneyline", "winner")):
        return "match_winner"
    return "other"


def _odds_summary(payload: Any) -> dict[str, Any]:
    rows = []
    seen = set()
    buckets = Counter()
    markets = Counter()
    for row, market in _walk_market_rows(payload):
        outcome = _outcome_text(row)
        price = _price(row)
        key = (market, outcome, price, json.dumps(_line_fields(row), sort_keys=True, default=str))
        if key in seen:
            continue
        seen.add(key)
        bucket = _market_bucket(market, outcome)
        buckets[bucket] += 1
        markets[market or "<unnamed>"] += 1
        if len(rows) < 120:
            rows.append({
                "market": market,
                "bucket": bucket,
                "outcome": outcome,
                "price": price,
                "fields": _line_fields(row),
            })
    return {
        "priced_rows": len(seen),
        "buckets": dict(sorted(buckets.items())),
        "market_names": dict(markets.most_common()),
        "rows": rows,
    }


def _stat_key_inventory(payload: Any) -> dict[str, Any]:
    keys = Counter()
    interesting = Counter()
    wanted = ("ace", "double", "serve", "break", "game", "set", "return", "point")

    def walk(value: Any):
        if isinstance(value, dict):
            for key, child in value.items():
                keys[str(key)] += 1
                normalized = str(key).casefold().replace("_", " ")
                if any(token in normalized for token in wanted):
                    interesting[str(key)] += 1
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return {
        "interesting_keys": dict(interesting.most_common()),
        "all_keys_sample": [name for name, _ in keys.most_common(120)],
    }


def _category_name(category: dict[str, Any]) -> str:
    nested = category.get("category") if isinstance(category.get("category"), dict) else {}
    return str(
        first_present(category, "name", "title", "slug")
        or first_present(nested, "name", "title", "slug")
        or ""
    )


def _discover_day(client: RapidTennisClient, day: date, max_events: int) -> list[dict[str, Any]]:
    rows = []
    categories = client.calendar_categories(day)
    for category in categories:
        category_id = client._category_id(category)
        if category_id is None:
            continue
        category_name = _category_name(category)
        for raw in client.category_events(category_id, day):
            rows.append(_event_summary(client, raw, category_id, category_name))
            rows[-1]["_raw"] = raw
            if len(rows) >= max_events:
                return rows
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-requests", type=int, default=80)
    parser.add_argument("--days-ahead", type=int, default=2)
    parser.add_argument("--days-back", type=int, default=2)
    parser.add_argument("--max-events-per-day", type=int, default=500)
    parser.add_argument("--odds-samples", type=int, default=10)
    parser.add_argument("--stats-samples", type=int, default=4)
    parser.add_argument("--out", default=".cache/tbt/provider-probe/provider_probe_report.json")
    parser.add_argument("--markdown", default=".cache/tbt/provider-probe/provider_probe_report.md")
    args = parser.parse_args()

    client = RapidTennisClient(request_budget=None)
    client.request_limit = max(1, args.max_requests)
    today = datetime.now(timezone.utc).date()
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider_host": client.cfg.rapidapi_host,
        "read_only": True,
        "request_cap": client.request_limit,
        "days": {},
        "summary": {},
        "doubles_samples": [],
        "odds_samples": [],
        "statistics_samples": [],
        "notes": [
            "No canonical history or prediction release is modified.",
            "Doubles are inspected from raw calendar/category events before the singles filter.",
            "Known event odds/statistics endpoints are probed; undocumented team routes are not guessed.",
        ],
    }

    all_events: list[dict[str, Any]] = []
    error = None
    try:
        start = today - timedelta(days=max(0, args.days_back))
        end = today + timedelta(days=max(0, args.days_ahead))
        day = start
        while day <= end:
            try:
                rows = _discover_day(client, day, args.max_events_per_day)
            except (ProviderError, RequestBudgetExceeded) as exc:
                report["days"][day.isoformat()] = {"error": str(exc)}
                if isinstance(exc, RequestBudgetExceeded):
                    break
                day += timedelta(days=1)
                continue
            counts = Counter(row["kind"] for row in rows)
            report["days"][day.isoformat()] = {
                "events": len(rows),
                "kinds": dict(counts),
                "finished": sum(row["status"] == "finished" for row in rows),
            }
            all_events.extend(rows)
            day += timedelta(days=1)

        counts = Counter(row["kind"] for row in all_events)
        doubles = [row for row in all_events if row["kind"] in {"doubles", "mixed_doubles"}]
        singles = [row for row in all_events if row["kind"] == "singles"]
        report["summary"] = {
            "events": len(all_events),
            "kinds": dict(counts),
            "doubles_with_side_ids": sum(bool(row["home"].get("id") and row["away"].get("id")) for row in doubles),
            "doubles_with_member_arrays": sum(bool(row["home"].get("member_count") or row["away"].get("member_count")) for row in doubles),
            "doubles_with_slash_names": sum("/" in row["home"].get("name", "") or "/" in row["away"].get("name", "") for row in doubles),
        }
        for row in doubles[:8]:
            sample = {k: v for k, v in row.items() if k != "_raw"}
            report["doubles_samples"].append(sample)

        # Prioritise upcoming doubles, then upcoming singles. This tells us whether
        # provider-1 has usable Match Winner / props / totals on the exact formats we need.
        now_ts = datetime.now(timezone.utc)
        def upcomingish(row: dict[str, Any]) -> bool:
            if row["status"] == "finished":
                return False
            text = row.get("scheduled_at") or ""
            try:
                return datetime.fromisoformat(text).astimezone(timezone.utc) >= now_ts - timedelta(hours=12)
            except Exception:
                return True

        odds_candidates = [row for row in doubles if upcomingish(row)] + [row for row in singles if upcomingish(row)]
        used_ids = set()
        for row in odds_candidates:
            if len(report["odds_samples"]) >= max(0, args.odds_samples):
                break
            event_id = row.get("event_id") or ""
            if not event_id or event_id in used_ids:
                continue
            used_ids.add(event_id)
            try:
                payload = client.event_odds(event_id, provider_id=1)
                odds = _odds_summary(payload)
                report["odds_samples"].append({
                    "event_id": event_id,
                    "kind": row["kind"],
                    "tournament": row["tournament"],
                    "home": row["home"].get("name"),
                    "away": row["away"].get("name"),
                    "odds": odds,
                })
            except (ProviderError, RequestBudgetExceeded) as exc:
                report["odds_samples"].append({"event_id": event_id, "kind": row["kind"], "error": str(exc)})
                if isinstance(exc, RequestBudgetExceeded):
                    break

        # Statistics are post-match. Prefer doubles so we learn whether pair events
        # expose aces/serve/break-point data at all, then add singles for comparison.
        finished_doubles = [row for row in doubles if row["status"] == "finished"]
        finished_singles = [row for row in singles if row["status"] == "finished"]
        stat_candidates = finished_doubles + finished_singles
        used_ids.clear()
        for row in stat_candidates:
            if len(report["statistics_samples"]) >= max(0, args.stats_samples):
                break
            event_id = row.get("event_id") or ""
            if not event_id or event_id in used_ids:
                continue
            used_ids.add(event_id)
            try:
                payload = client.event_statistics(event_id)
                report["statistics_samples"].append({
                    "event_id": event_id,
                    "kind": row["kind"],
                    "tournament": row["tournament"],
                    "home": row["home"].get("name"),
                    "away": row["away"].get("name"),
                    "inventory": _stat_key_inventory(payload),
                })
            except (ProviderError, RequestBudgetExceeded) as exc:
                report["statistics_samples"].append({"event_id": event_id, "kind": row["kind"], "error": str(exc)})
                if isinstance(exc, RequestBudgetExceeded):
                    break
    except Exception as exc:  # preserve a report even when provider shape changes
        error = f"{type(exc).__name__}: {exc}"
        report["fatal_error"] = error
    finally:
        report["requests_used"] = client.request_count
        report["rate_limit_remaining"] = client.rate_limit_remaining
        client.close()

    # Aggregate discovered market capabilities across sampled events.
    bucket_by_kind: dict[str, Counter] = defaultdict(Counter)
    market_names_by_kind: dict[str, Counter] = defaultdict(Counter)
    for sample in report["odds_samples"]:
        odds = sample.get("odds") if isinstance(sample, dict) else None
        if not isinstance(odds, dict):
            continue
        kind = str(sample.get("kind") or "unknown")
        for bucket, count in (odds.get("buckets") or {}).items():
            bucket_by_kind[kind][bucket] += int(count)
        for name, count in (odds.get("market_names") or {}).items():
            market_names_by_kind[kind][name] += int(count)
    report["market_capabilities"] = {
        kind: {
            "buckets": dict(counter),
            "market_names": dict(market_names_by_kind[kind].most_common()),
        }
        for kind, counter in bucket_by_kind.items()
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        "# BlinQ TennisApi provider probe",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Requests used: **{report.get('requests_used', 0)} / {report['request_cap']}**",
        f"Provider: `{report['provider_host']}`",
        "",
        "## Event discovery",
        "",
        f"- Total raw events inspected: **{report.get('summary', {}).get('events', 0)}**",
    ]
    for kind, count in sorted((report.get("summary", {}).get("kinds") or {}).items()):
        lines.append(f"- {kind}: **{count}**")
    lines += [
        f"- doubles with side/team IDs: **{report.get('summary', {}).get('doubles_with_side_ids', 0)}**",
        f"- doubles with explicit member arrays: **{report.get('summary', {}).get('doubles_with_member_arrays', 0)}**",
        f"- doubles with slash pair names: **{report.get('summary', {}).get('doubles_with_slash_names', 0)}**",
        "",
        "## Sampled odds capabilities",
        "",
    ]
    for kind, values in sorted((report.get("market_capabilities") or {}).items()):
        lines.append(f"### {kind}")
        buckets = values.get("buckets") or {}
        if buckets:
            for bucket, count in sorted(buckets.items()):
                lines.append(f"- {bucket}: {count} priced rows")
        else:
            lines.append("- no priced rows found in sampled events")
        lines.append("")
    lines += [
        "## Interpretation",
        "",
        "- Aces / Sets / Games can become odds-backed only if those market buckets appear with real provider lines and prices.",
        "- Doubles can move to a separate model only after pair/team/member identity is stable in the captured samples.",
        "- This probe deliberately does not guess undocumented team endpoint routes.",
    ]
    if error:
        lines += ["", f"Fatal probe error: `{error}`"]
    Path(args.markdown).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "report": str(out),
        "requests_used": report.get("requests_used"),
        "summary": report.get("summary"),
        "market_capabilities": report.get("market_capabilities"),
        "fatal_error": report.get("fatal_error"),
    }, ensure_ascii=False, indent=2))
    if error:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
