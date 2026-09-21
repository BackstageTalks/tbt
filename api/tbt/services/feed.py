"""Small, authenticated serving snapshot. No database or ML dependency."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def empty_feed():
    return {
        "schema": 1,
        "generated_at": None,
        "model": None,
        "upcoming": [],
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
    if target.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("Serving feed exceeds the 10 MB cap")

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
    """Never present started matches or an old feed as fresh upcoming picks."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid serving feed root")

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("visible_feed requires timezone-aware now")
    now = now.astimezone(timezone.utc)

    result = dict(payload)

    # Every public pre-match representation must obey the same runtime clock.
    # Historically only `upcoming` was filtered, leaving already-started rows in
    # TOP/PRIME/VALUE/ACES/SG arrays until the next data publication.
    prematch_keys = (
        "upcoming", "top_daily_picks", "prime_picks", "value_picks",
        "doubles_picks", "ace_picks", "sg_picks",
    )
    for key in prematch_keys:
        rows = payload.get(key, [])
        if not isinstance(rows, list):
            if key == "upcoming":
                raise ValueError("Invalid serving feed: upcoming")
            continue
        visible = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw = row.get("scheduled_at") or row.get("start_at") or row.get("start_time") or row.get("date")
            try:
                starts_at = _parse_utc_timestamp(raw, "scheduled_at")
            except ValueError:
                # A pre-match pick with no trustworthy start time is unsafe to
                # present as current. Hide it rather than serving stale content.
                continue
            if starts_at > now:
                visible.append(row)
        result[key] = visible

    stamp = payload.get("generated_at")
    if not stamp:
        result["stale"] = True
    else:
        generated_at = _parse_utc_timestamp(stamp, "generated_at")
        result["stale"] = (
            now - generated_at
        ).total_seconds() > 12 * 3600

    return result
