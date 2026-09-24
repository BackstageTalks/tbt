"""Read-only hourly match-status overlay for already published BlinQ picks.

This layer is presentation only. It never settles the immutable prediction ledger,
calculates ROI, or changes the pre-match forecast or its odds.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BETTING_ZONE = ZoneInfo("Europe/Bratislava")
OFFER_SECTIONS = (
    "top_daily_picks", "prime_picks", "value_picks",
    "doubles_picks", "ace_picks", "sg_picks",
)
TERMINAL = {"finished", "retired", "cancelled"}
VALID_STATES = TERMINAL | {"scheduled", "started", "postponed"}

_FINISHED = {"finished", "ended", "completed", "ft", "final"}
_LIVE = {"inprogress", "in_progress", "in progress", "live", "started", "playing",
         "1st set", "2nd set", "3rd set", "4th set", "5th set",
         "interrupted", "paused", "suspended"}
_RETIRED = {"retired", "retirement", "abandoned", "player retired"}
_CANCELLED = {"cancelled", "canceled", "walkover", "withdrawn", "wo"}
_POSTPONED = {"postponed", "delayed", "rescheduled"}


def betting_day(now: datetime, start_hour: int = 6) -> str:
    local = now.astimezone(BETTING_ZONE)
    if local.hour < start_hour:
        local -= timedelta(days=1)
    return local.date().isoformat()


def _utc_time(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        result = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return result.astimezone(timezone.utc) if result.tzinfo else None


def _identity(row: dict) -> tuple[str, str]:
    p1 = row.get("player1") if isinstance(row.get("player1"), dict) else {}
    p2 = row.get("player2") if isinstance(row.get("player2"), dict) else {}
    return str(p1.get("id") or "").strip(), str(p2.get("id") or "").strip()


def tracked_matches(feed: dict, now: datetime) -> dict[str, dict]:
    """Track the union of published daily categories without double-counting events."""
    current_day = betting_day(now)
    tracked: dict[str, dict] = {}
    for key in OFFER_SECTIONS:
        for row in feed.get(key, []) or []:
            if not isinstance(row, dict):
                continue
            event_id = str(row.get("event_id") or "").strip()
            p1, p2 = _identity(row)
            when = _utc_time(row.get("scheduled_at"))
            if (not event_id or not p1 or not p2 or p1 == p2 or
                    not when or betting_day(when) != current_day):
                continue
            if event_id in tracked:
                # Provider IDs reused with a different pair must never inherit
                # a previous event's result.
                if set(tracked[event_id]["players"]) != {p1, p2}:
                    tracked.pop(event_id, None)
                continue
            tracked[event_id] = {
                "players": [p1, p2],
                "scheduled_at": when.isoformat(),
                "tour": str(row.get("tour") or "").lower(),
            }
    return tracked


def event_id(event: dict) -> str:
    return str(event.get("id") or event.get("eventId") or event.get("event_id") or "").strip()


def _event_pair(event: dict) -> tuple[str, str]:
    home = event.get("homeTeam") if isinstance(event.get("homeTeam"), dict) else {}
    away = event.get("awayTeam") if isinstance(event.get("awayTeam"), dict) else {}
    return str(home.get("id") or "").strip(), str(away.get("id") or "").strip()


def normalized_status(event: dict) -> str | None:
    raw = event.get("status")
    if isinstance(raw, dict):
        texts = [str(raw.get(key) or "").casefold().strip()
                 for key in ("type", "description", "name")]
    else:
        texts = [str(raw or "").casefold().strip()]
    # A retirement description can accompany status.type=finished.
    if any(text in _RETIRED or "retir" in text for text in texts):
        return "retired"
    if any(text in _CANCELLED for text in texts):
        return "cancelled"
    if any(text in _POSTPONED for text in texts):
        return "postponed"
    if any(text in _FINISHED for text in texts):
        return "finished"
    if any(text in _LIVE or "set " in text for text in texts):
        return "started"
    if any(text in {"notstarted", "not started", "scheduled", "upcoming"} for text in texts):
        return "scheduled"
    return None


def observed_event(event: dict, expected: dict, scanned_at: str) -> dict | None:
    """Return a verified state only when provider event ID and both players match."""
    home, away = _event_pair(event)
    if not home or not away or home == away or {home, away} != set(expected["players"]):
        return None
    status = normalized_status(event)
    if not status:
        return None
    winner_id = None
    if status == "finished":
        explicit = event.get("winnerId") or event.get("winner_id") or event.get("winnerTeamId")
        code = str(event.get("winnerCode") or event.get("winner_code") or "").strip().lower()
        from_code = home if code in {"1", "home", "player1", "p1"} else (
            away if code in {"2", "away", "player2", "p2"} else None
        )
        if explicit and str(explicit) not in {home, away}:
            return None
        if explicit and from_code and str(explicit) != from_code:
            return None
        winner_id = str(explicit) if explicit else from_code
    return {"status": status, "winner_id": winner_id, "observed_at": scanned_at,
            "players": sorted([home, away])}


def status_snapshot(feed: dict, previous: dict | None, events: list[dict],
                    *, now: datetime, partial: bool = False) -> dict:
    """Merge provider observations and preserve confirmed terminal results."""
    tracked = tracked_matches(feed, now)
    previous = previous if isinstance(previous, dict) and previous.get("betting_day") == betting_day(now) else {}
    prior_items = previous.get("items") if isinstance(previous.get("items"), dict) else {}
    scanned_at = now.astimezone(timezone.utc).isoformat()
    current: dict[str, dict] = {}
    for key, info in tracked.items():
        old = prior_items.get(key)
        if not isinstance(old, dict) or old.get("status") not in VALID_STATES:
            continue
        if set(old.get("players") or []) != set(info["players"]):
            continue
        current[key] = dict(old)
    for event in events:
        if not isinstance(event, dict):
            continue
        key = event_id(event)
        if key not in tracked:
            continue
        observation = observed_event(event, tracked[key], scanned_at)
        if not observation:
            continue
        old = current.get(key, {})
        # A later provider reclassification must not silently flip a finalized
        # public result. Canonical ledger settlement remains separate.
        if old.get("status") in TERMINAL:
            continue
        if old.get("status") == "started" and observation["status"] == "scheduled":
            continue
        current[key] = observation
    return {
        "schema": 1, "betting_day": betting_day(now), "scanned_at": scanned_at,
        "partial": bool(partial), "items": current,
        "tracked": len(tracked), "observed": len(current),
    }


def pending_calendar_dates(tracked: dict, snapshot: dict, now: datetime) -> list:
    """Only look up results for overdue matches absent from the LIVE endpoint."""
    items = snapshot.get("items") or {}
    dates = set()
    for key, row in tracked.items():
        state = (items.get(key) or {}).get("status")
        when = _utc_time(row.get("scheduled_at"))
        if state in TERMINAL or not when or now - when < timedelta(minutes=45):
            continue
        dates.add(when.date())
        dates.add(when.astimezone(BETTING_ZONE).date())
    return sorted(dates, reverse=True)[:3]
