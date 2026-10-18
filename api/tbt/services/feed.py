"""Small, authenticated serving snapshot. No database or ML dependency."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


MAX_FEED_BYTES = 20 * 1024 * 1024  # Guarded headroom for verified ~16.9 MB 2026-10-12 release


def _betting_day_key(moment, *, timezone_name="Europe/Bratislava", start_hour=6):
    if moment.tzinfo is None:
        raise ValueError("betting day requires timezone-aware datetime")
    local = moment.astimezone(ZoneInfo(timezone_name))
    boundary = local.replace(hour=int(start_hour), minute=0, second=0, microsecond=0)
    if local < boundary:
        boundary -= timedelta(days=1)
    return boundary.date().isoformat()


def _row_betting_day(row, *, timezone_name="Europe/Bratislava", start_hour=6):
    if not isinstance(row, dict):
        return ""
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    explicit = str(row.get("betting_day") or betting.get("betting_day") or "").strip()
    if explicit:
        return explicit
    raw = row.get("scheduled_at") or row.get("start_at") or row.get("start_time") or row.get("date")
    try:
        starts_at = _parse_utc_timestamp(raw, "scheduled_at")
    except ValueError:
        return ""
    return _betting_day_key(starts_at, timezone_name=timezone_name, start_hour=start_hour)

def empty_feed():
    return {
        "schema": 1,
        "generated_at": None,
        "model": None,
        "upcoming": [],
        "top200_picks": [],
        "top_daily_picks": [],
        "prime_picks": [],
        "value_picks": [],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
        "market_selection": {},
        "results": [],
        "performance": {},
        "betting_performance": {},
        "results_meta": {"settled_total": 0, "returned": 0, "limit": 1000},
        "history": {},
        "ready": False,
    }


def _parse_utc_timestamp(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid serving feed timestamp: {field}")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid serving feed timestamp: {field}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"Naive serving feed timestamp: {field}")
    return parsed.astimezone(timezone.utc)


def _validate_prediction_row(row, *, require_result=False):
    if not isinstance(row, dict):
        raise ValueError("Invalid serving feed row")

    for key in ("event_id", "scheduled_at", "player1", "player2"):
        if key not in row:
            raise ValueError(f"Invalid serving feed row: missing {key}")

    if not str(row.get("event_id") or "").strip():
        raise ValueError("Invalid serving feed row: empty event_id")

    _parse_utc_timestamp(row.get("scheduled_at"), "scheduled_at")

    for player_key in ("player1", "player2"):
        player = row.get(player_key)
        if not isinstance(player, dict):
            raise ValueError(f"Invalid serving feed row: {player_key}")
        if not str(player.get("id") or "").strip():
            raise ValueError(f"Invalid serving feed row: {player_key}.id")

    if require_result:
        result = row.get("result")
        if not isinstance(result, dict):
            raise ValueError("Invalid serving result row")
        if not str(result.get("winner_id") or "").strip():
            raise ValueError("Invalid serving result row: winner_id")


def read_feed(path):
    target = Path(path)
    if not target.is_file():
        return empty_feed()
    if target.stat().st_size > MAX_FEED_BYTES:
        raise ValueError(f"Serving feed exceeds the {MAX_FEED_BYTES // (1024 * 1024)} MB cap")

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid serving feed JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("Invalid serving feed root")
    if payload.get("schema") != 1:
        raise ValueError("Unsupported serving schema")

    for key in ("upcoming", "results"):
        if not isinstance(payload.get(key), list):
            raise ValueError(f"Invalid serving feed: {key}")

    stamp = payload.get("generated_at")
    if stamp is not None:
        _parse_utc_timestamp(stamp, "generated_at")

    for row in payload["upcoming"]:
        _validate_prediction_row(row, require_result=False)
    for row in payload["results"]:
        _validate_prediction_row(row, require_result=True)

    return payload


def visible_feed(payload, now=None):
    """Serve future discovery and today's public 06:00-to-06:00 offer.

    The internal betting-day interval remains [06:00, next 06:00), with the
    ending 06:00 excluded. Public TOP/ACCA/VALUE/other daily tabs additionally
    show only fixtures dated on the *opening calendar day* in Bratislava.
    After-midnight fixtures in the internal interval stay in the raw snapshot
    but are not displayed as tomorrow's matches on today's page.
    """
    if not isinstance(payload, dict):
        raise ValueError("Invalid serving feed root")

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("visible_feed requires timezone-aware now")
    now = now.astimezone(timezone.utc)
    day = _betting_day_key(now)

    result = dict(payload)
    # Legacy releases may contain TOP200 rows; the public product is retired.
    # Never serve its active picks, while preserving historical settled Results.
    result["top200_picks"] = []

    upcoming = payload.get("upcoming", [])
    if not isinstance(upcoming, list):
        raise ValueError("Invalid serving feed: upcoming")
    future=[]
    for row in upcoming:
        if not isinstance(row, dict):
            continue
        raw = row.get("scheduled_at") or row.get("start_at") or row.get("start_time") or row.get("date")
        try:
            starts_at = _parse_utc_timestamp(raw, "scheduled_at")
        except ValueError:
            continue
        if starts_at > now:
            future.append(row)
    result["upcoming"] = future

    # Internal settlement/publication remains 06:00 -> next-day 05:59:59.
    # The public TODAY board must not show rows dated tomorrow, even when the
    # internal betting-day window includes them (e.g. 19 Oct 04:30 and 05:00
    # before the 19 Oct 06:00 rollover). Use actual scheduled_at, not a
    # potentially wrong explicit betting_day, to enforce BOTH conditions.
    # This is presentation filtering only; retain raw history unchanged.
    local_zone = ZoneInfo("Europe/Bratislava")

    def scheduled_for_public_offer_day(row):
        if not isinstance(row, dict):
            return False
        raw = row.get("scheduled_at") or row.get("start_at") or row.get("start_time") or row.get("date")
        try:
            scheduled = _parse_utc_timestamp(raw, "scheduled_at")
        except ValueError:
            return False
        local_date = scheduled.astimezone(local_zone).date().isoformat()
        return local_date == day and _betting_day_key(scheduled) == day

    for key in ("top_daily_picks", "prime_picks", "value_picks", "doubles_picks", "ace_picks", "sg_picks"):
        rows = payload.get(key, [])
        if not isinstance(rows, list):
            continue
        result[key] = [row for row in rows if scheduled_for_public_offer_day(row)]

    stamp = payload.get("generated_at")
    if not stamp:
        result["stale"] = True
    else:
        generated_at = _parse_utc_timestamp(stamp, "generated_at")
        # The serving offer is refreshed each betting morning. A fixed 12h
        # timer incorrectly flags a healthy 06:00 feed as broken after 18:00.
        # Fail closed after the next 06:00 Bratislava boundary, or when an
        # implausibly future-dated feed indicates clock/deployment corruption.
        result["stale"] = (
            _betting_day_key(generated_at) != day
            or generated_at > now + timedelta(minutes=5)
        )
    result["daily_offer_day"] = day
    return result
