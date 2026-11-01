"""Read-only bounded comparison of TennisApi calendar and season-page coverage.

Uses existing RapidTennisClient shared paid quota/throttle. No CDB writes or
model changes. Tournament last-page endpoint is zero-indexed. Do not switch
ingestion to the season path unless exact IDs and match metadata agree.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.errors import ProviderError
from tbt.providers.rapidapi import RapidTennisClient


def event_id(event):
    value = event.get("id", event.get("eventId"))
    return str(value) if value is not None and str(value) else None


def native_context(event):
    tournament = event.get("tournament") or {}
    if not isinstance(tournament, dict):
        return None
    unique = tournament.get("uniqueTournament") or {}
    season = event.get("season") or {}
    if not isinstance(unique, dict) or not isinstance(season, dict):
        return None
    try:
        unique_id = int(unique["id"])
        season_id = int(season["id"])
        timestamp = int(event["startTimestamp"])
        if timestamp <= 0:
            return None
        day = datetime.fromtimestamp(timestamp, timezone.utc).date()
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    home, away = event.get("homeTeam") or {}, event.get("awayTeam") or {}
    if not isinstance(home, dict) or not isinstance(away, dict):
        return None
    status = event.get("status") or {}
    if not isinstance(status, dict):
        return None
    label = str(event.get("eventType") or event.get("type") or "").lower()
    if label in {"singles", "single"}:
        discipline = "singles"
    elif label in {"doubles", "double"}:
        discipline = "doubles"
    else:
        discipline = "unconfirmed"
    return {"unique_tournament": unique_id, "season": season_id,
            "actual_utc_day": day.isoformat(),
            "home": str(home.get("id") or ""),
            "away": str(away.get("id") or ""),
            "discipline": discipline,
            "status": str(status.get("type") or "").lower()}


def validate_rows(rows, unique_id, season_id, first, last):
    accepted, review = {}, []
    for event in rows:
        if not isinstance(event, dict):
            raise ProviderError("Non-object season/calendar event")
        eid = event_id(event)
        if eid is None:
            raise ProviderError("Source event ID missing")
        ctx = native_context(event)
        if ctx is None:
            review.append({"event_id": eid, "reason": "incomplete_native_context"})
            continue
        if ctx["unique_tournament"] != unique_id or ctx["season"] != season_id:
            continue
        day = date.fromisoformat(ctx["actual_utc_day"])
        if not first <= day <= last:
            continue
        if not ctx["home"] or not ctx["away"] or ctx["home"] == ctx["away"]:
            review.append({"event_id": eid, "reason": "invalid_participants"})
            continue
        if ctx["discipline"] == "unconfirmed" or ctx["status"] in {
            "postponed", "cancelled", "canceled", "interrupted"
        }:
            review.append({"event_id": eid, "reason": "discipline_or_status_review"})
            continue
        if eid in accepted and accepted[eid] != ctx:
            raise ProviderError("Conflicting native event ID within one method")
        accepted[eid] = ctx
    return accepted, review


def compare(calendar_rows, season_rows, *, unique_id, season_id, first, last,
            calendar_calls, season_calls, complete):
    calendar, cr = validate_rows(calendar_rows, unique_id, season_id, first, last)
    season, sr = validate_rows(season_rows, unique_id, season_id, first, last)
    common = calendar.keys() & season.keys()
    mismatched = sorted(eid for eid in common if calendar[eid] != season[eid])
    absent = sorted(calendar.keys() - season.keys())
    extra = sorted(season.keys() - calendar.keys())
    safe = bool(complete and not (mismatched or absent or extra or cr or sr))
    return {
        "status": "EXACT_COVERAGE_VERIFIED" if safe else "REVIEW_REQUIRED",
        "unique_tournament_id": unique_id, "season_id": season_id,
        "date_from": first.isoformat(), "date_to": last.isoformat(),
        "calendar_requests_including_retries": calendar_calls,
        "season_requests_including_retries": season_calls,
        "calendar_event_ids": sorted(calendar), "season_event_ids": sorted(season),
        "calendar_missing_from_season": absent, "season_missing_from_calendar": extra,
        "metadata_mismatch_event_ids": mismatched,
        "calendar_review": cr, "season_review": sr,
        "season_pagination_complete": bool(complete),
        "switch_allowed": False,  # Explicit later gate; this script never switches ingestion.
        "provider_calls_from_comparison_only": True,
    }


def _rows(payload):
    if payload == {}:
        return []
    return RapidTennisClient._response_rows(payload, "events")


def probe(provider, witness_id, first, last, *, max_pages=3):
    if not 1 <= max_pages <= 3 or (last-first).days not in (0, 1):
        raise ValueError("Probe requires <=2 calendar days and <=3 season pages")
    before = provider.request_count
    detail = provider._get(f"/api/tennis/event/{witness_id}", enrichment=True)
    raw = detail.get("event", detail)
    if not isinstance(raw, dict) or event_id(raw) != str(witness_id):
        raise ProviderError("Witness event identity changed")
    ctx = native_context(raw)
    if ctx is None or not first <= date.fromisoformat(ctx["actual_utc_day"]) <= last:
        raise ProviderError("Witness lacks confirmed source tournament/season/time")
    tournament = raw.get("tournament") or {}
    category = tournament.get("category") or {}
    try:
        category_id = int(category["id"])
    except (KeyError, TypeError, ValueError):
        raise ProviderError("Witness category ID unavailable")
    unique_id, season_id = ctx["unique_tournament"], ctx["season"]
    calendar_rows = []
    for offset in range((last-first).days + 1):
        day = first + timedelta(days=offset)
        categories = provider.calendar_categories(day)
        if category_id not in {provider._category_id(x) for x in categories}:
            raise ProviderError("Witness category missing from calendar day")
        calendar_rows.extend(provider.category_events(category_id, day))
    calendar_calls = provider.request_count-before
    season_rows, complete = [], False
    for page in range(max_pages + 1):
        payload = provider._get(
            f"/api/tennis/tournament/{unique_id}/season/{season_id}/events/last/{page}",
            enrichment=True,
        )
        rows = _rows(payload)
        if not rows:
            complete = True
            break
        season_rows.extend(rows)
    result = compare(calendar_rows, season_rows, unique_id=unique_id,
                     season_id=season_id, first=first, last=last,
                     calendar_calls=calendar_calls,
                     season_calls=provider.request_count-before-calendar_calls,
                     complete=complete)
    result["witness_event_id"] = str(witness_id)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute-live", action="store_true",
                    help="Required opt-in; no live API call by default.")
    ap.add_argument("--witness-event-id", default="7115726")
    ap.add_argument("--start", default="2016-07-09")
    ap.add_argument("--end", default="2016-07-10")
    ap.add_argument("--max-requests", type=int, default=12)
    ap.add_argument("--max-pages", type=int, default=3)
    ap.add_argument("--output", default=".cache/tbt/tournament-probe/report.json")
    args = ap.parse_args()
    if not args.execute_live:
        raise SystemExit("Read-only probe prepared; explicit --execute-live required.")
    if not 1 <= args.max_requests <= 12:
        raise SystemExit("Read-only probe maximum is 12 paid attempts, including retries.")
    client = RapidTennisClient()
    client.request_limit = min(client.request_limit, args.max_requests)
    try:
        result = probe(client, args.witness_event_id, date.fromisoformat(args.start),
                       date.fromisoformat(args.end), max_pages=args.max_pages)
        result["actual_paid_attempts"] = client.request_count
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, sort_keys=True))
    finally:
        client.close()


if __name__ == "__main__":
    main()
