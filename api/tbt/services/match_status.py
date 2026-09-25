"""Lightweight post-start status refresh for BlinQ daily prediction rows.

The public prediction feed is immutable between full data refreshes, but users do
not need to wait for that refresh to see a finished match.  This module performs
an inexpensive runtime-only reconciliation against the tennis provider:

* pre-start rows remain silent in the UI;
* scheduled rows are shown as STARTED by the browser once their start time passes;
* a small hourly worker checks only unresolved, already-started fixtures;
* settled fixtures are persisted as win / loss / retired and are never re-queried.

No model probabilities, odds, publication commitments or historical training data
are changed here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re
from typing import Any


TERMINAL_STATUSES = {"win", "loss", "retired"}

_FEED_ROW_KEYS = (
    "upcoming",
    "prime_picks",
    "top_daily_picks",
    "top_daily",
    "daily_picks",
    "value_picks",
    "value",
    "doubles_picks",
    "doubles",
    "ace_picks",
    "aces",
    "ace_markets",
    "sg_picks",
    "sets_games",
    "set_game_picks",
    "board_upcoming",
    "board_results",
)


def _event_id(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("event_id") or row.get("id") or row.get("match_id") or "").strip()


def _parse_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _selection_id(row: dict[str, Any]) -> str:
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    return str(
        betting.get("selection_id")
        or row.get("winner_id")
        or row.get("selection_id")
        or ""
    ).strip()


def _player_id(row: dict[str, Any], key: str) -> str:
    player = row.get(key) if isinstance(row.get(key), dict) else {}
    return str(player.get("id") or "").strip()


def prediction_rows(feed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return one best representative row per provider event id."""
    out: dict[str, dict[str, Any]] = {}

    def add_rows(rows: Any) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            eid = _event_id(row)
            if not eid:
                continue
            existing = out.get(eid)
            # Prefer rows that carry both a selection and player identity.
            quality = int(bool(_selection_id(row))) + int(bool(_player_id(row, "player1")))
            old_quality = (
                int(bool(_selection_id(existing))) + int(bool(_player_id(existing, "player1")))
                if isinstance(existing, dict)
                else -1
            )
            if existing is None or quality > old_quality:
                out[eid] = row

    for key in _FEED_ROW_KEYS:
        add_rows(feed.get(key))

    markets = feed.get("markets")
    if isinstance(markets, dict):
        for rows in markets.values():
            add_rows(rows)

    return out


def event_ids_from_feed(feed: dict[str, Any]) -> set[str]:
    return set(prediction_rows(feed))


def _provider_rows(payload: Any) -> list[dict[str, Any]]:
    """Extract event-shaped rows from common TennisApi wrappers."""
    found: list[dict[str, Any]] = []

    def walk(value: Any, depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
            return
        if not isinstance(value, dict):
            return
        if (
            value.get("id") is not None
            and isinstance(value.get("homeTeam"), dict)
            and isinstance(value.get("awayTeam"), dict)
        ):
            found.append(value)
            return
        for key in ("events", "data", "result", "results", "response", "matches",
                    "previousEvent", "previous", "lastEvent", "lastMatch",
                    "previousMatch", "event", "near", "last"):
            child = value.get(key)
            if isinstance(child, (list, dict)):
                walk(child, depth + 1)

    walk(payload)
    return found


def _provider_event_id(event: dict[str, Any]) -> str:
    return str(event.get("id") or event.get("eventId") or event.get("event_id") or "").strip()


def _status_text(event: dict[str, Any]) -> str:
    status = event.get("status")
    parts: list[str] = []
    if isinstance(status, dict):
        parts.extend(
            str(status.get(key) or "")
            for key in ("type", "description", "name", "reason")
        )
    elif status is not None:
        parts.append(str(status))
    parts.extend(
        str(event.get(key) or "")
        for key in (
            "statusDescription",
            "status_description",
            "reason",
            "retirementReason",
            "retirement_reason",
        )
    )
    return " ".join(parts).strip().lower()


def classify_finished_event(
    row: dict[str, Any],
    event: dict[str, Any],
    *,
    checked_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Classify a provider event as win/loss/retired for the predicted side."""
    checked_at = checked_at or datetime.now(timezone.utc)
    status_text = _status_text(event)
    retirement_markers = (
        "retired",
        "retirement",
        "ret.",
        "retd",
        "abandoned due to injury",
    )
    retired = any(marker in status_text for marker in retirement_markers)

    winner_code = event.get("winnerCode")
    try:
        winner_code = int(winner_code)
    except (TypeError, ValueError):
        winner_code = 0

    finished = any(
        marker in status_text
        for marker in ("finished", "ended", "completed", "full time")
    ) or winner_code in {1, 2}

    if not finished and not retired:
        return None

    base = {
        "checked_at": checked_at.isoformat(),
        "provider_status": status_text[:120],
    }
    home = event.get("homeTeam") if isinstance(event.get("homeTeam"), dict) else {}
    away = event.get("awayTeam") if isinstance(event.get("awayTeam"), dict) else {}
    # A recycled or incorrectly mapped provider ID must never mark an
    # unrelated published pick as a loss (or retirement).
    feed_players = {_player_id(row, "player1"), _player_id(row, "player2")}
    provider_players = {str(home.get("id") or "").strip(), str(away.get("id") or "").strip()}
    if "" in feed_players or "" in provider_players or feed_players != provider_players:
        return None
    if retired:
        return {**base, "status": "retired"}

    provider_winner = ""
    if winner_code == 1:
        provider_winner = str(home.get("id") or "").strip()
    elif winner_code == 2:
        provider_winner = str(away.get("id") or "").strip()
    if not provider_winner:
        return None

    predicted = _selection_id(row)
    if not predicted:
        return None

    return {
        **base,
        "status": "win" if predicted == provider_winner else "loss",
        "winner_id": provider_winner,
    }


def _provider_error_code(error: Exception) -> str:
    """Only report a safe exception class and HTTP status, never URLs or payloads."""
    kind = type(error).__name__[:48]
    code = re.search(r"\bHTTP\s+([1-5]\d\d)\b", str(error))
    return f"{kind}_HTTP_{code.group(1)}" if code else kind


def scan_match_statuses(
    feed: dict[str, Any],
    provider: Any,
    previous_snapshot: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    max_checks: int = 30,
    lookback_hours: int = 36,
    max_near_checks: int = 12,
    min_start_age_minutes: int = 0,
    retry_after_minutes: int = 0,
) -> dict[str, Any]:
    """Settle verified events without trusting a consistently 404ing history route.

    TennisApi's /player/{id}/events/near is an alternate compact source for
    the closest previous/next match. It is NOT guaranteed to contain every
    historical match, so a missing event is left pending, never scored.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = prediction_rows(feed)
    prior = previous_snapshot if isinstance(previous_snapshot, dict) else {}
    existing = prior.get("statuses")
    existing = existing if isinstance(existing, dict) else {}
    statuses: dict[str, dict[str, Any]] = {
        str(eid): dict(value)
        for eid, value in existing.items()
        if eid in rows
        and isinstance(value, dict)
        and str(value.get("status") or "") in TERMINAL_STATUSES
    }

    cutoff = now - timedelta(hours=max(1, int(lookback_hours)))
    due: list[tuple[datetime, str, dict[str, Any]]] = []
    for eid, row in rows.items():
        if eid in statuses:
            continue
        scheduled = _parse_time(row.get("scheduled_at") or row.get("date"))
        if scheduled is None or scheduled > now or scheduled < cutoff:
            continue
        if not _player_id(row, "player1"):
            continue
        due.append((scheduled, eid, row))
    # The dashboard KPI counts picks, not distinct fixtures. Prioritize
    # today's unique TOP/winner-market event IDs, then yesterday's remaining
    # picks, then older/unfeatured fixtures. The provider is queried only
    # once per event, even when the same match appears in multiple sections.
    today = now.astimezone(ZoneInfo("Europe/Bratislava")).date()
    top_ids = {
        _event_id(row)
        for key in ("daily_picks", "top_daily_picks")
        for row in (feed.get(key) or [])
        if isinstance(row, dict) and _event_id(row)
    }
    focus_ids = top_ids | {
        _event_id(row)
        for key in ("prime_picks", "value_picks", "doubles_picks")
        for row in (feed.get(key) or [])
        if isinstance(row, dict) and _event_id(row)
    }

    def priority(item: tuple[datetime, str, dict[str, Any]]) -> int:
        scheduled, eid, _ = item
        day_delta = (today - scheduled.astimezone(ZoneInfo("Europe/Bratislava")).date()).days
        if eid in top_ids and day_delta == 0:
            return 0
        if eid in focus_ids and day_delta == 0:
            return 1
        if eid in top_ids and day_delta == 1:
            return 2
        if eid in focus_ids and day_delta == 1:
            return 3
        if eid in focus_ids:
            return 4
        if day_delta == 0:
            return 5
        return 6

    due.sort(key=lambda item: (priority(item), item[0], item[1]))
    recent_checks = prior.get("last_checked_at")
    recent_checks = recent_checks if isinstance(recent_checks, dict) else {}
    last_checked_at: dict[str, str] = {
        eid: str(recent_checks[eid])
        for _, eid, _ in due
        if eid in recent_checks and _parse_time(recent_checks[eid]) is not None
    }
    wait = timedelta(minutes=max(0, min(360, int(min_start_age_minutes))))
    cooldown = timedelta(minutes=max(0, min(360, int(retry_after_minutes))))
    checkable_now = sum(
        now >= scheduled + wait
        and (not cooldown or
             now >= (_parse_time(last_checked_at.get(eid)) or scheduled) + cooldown)
        for scheduled, eid, _ in due
    )
    focus_due = sum(eid in focus_ids for _, eid, _ in due)

    prior_errors = prior.get("provider_errors")
    prior_errors = prior_errors if isinstance(prior_errors, dict) else {}
    known_history_404 = int(prior_errors.get("ProviderError_HTTP_404") or 0) >= 2
    prefer_near = prior.get("preferred_route") == "near" or (
        known_history_404 and int(prior.get("successful_history") or 0) == 0
    )
    near_method = getattr(provider, "near_player_matches_for_status", None)
    near_cache: dict[str, Any] = {}
    max_near_checks = max(0, min(30, int(max_near_checks)))

    provider_errors: dict[str, int] = {}
    live_by_id: dict[str, dict[str, Any]] = {}
    nominal_requests = 0
    request_count_before = getattr(provider, "request_count", None)
    if due:
        try:
            nominal_requests += 1
            live_events = provider.live_events()
            live_by_id = {
                _provider_event_id(event): event
                for event in live_events
                if isinstance(event, dict) and _provider_event_id(event)
            }
        except Exception as exc:
            code = _provider_error_code(exc)
            provider_errors[code] = provider_errors.get(code, 0) + 1

    checked = skipped_live = successful_history = matched_events = 0
    newly_resolved = consecutive_errors = near_attempts = unmatched = 0
    deferred_recent = deferred_cooldown = 0
    next_due_id = ""
    max_checks = max(0, min(120, int(max_checks)))
    cursor = str(prior.get("next_due_id") or "")
    # Rotate only inside a matching priority bucket. A cursor pointing to an
    # old background match must never jump ahead of today's fresh TOP picks.
    cursor_idx = next((i for i, (_, eid, _) in enumerate(due) if eid == cursor), -1)
    if cursor_idx >= 0:
        bucket = priority(due[cursor_idx])
        lo = next(i for i, item in enumerate(due) if priority(item) == bucket)
        hi = next((i for i in range(cursor_idx + 1, len(due))
                   if priority(due[i]) != bucket), len(due))
        ordered = due[:lo] + due[cursor_idx:hi] + due[lo:cursor_idx] + due[hi:]
    else:
        ordered = due

    for position, (_, eid, row) in enumerate(ordered):
        if checked >= max_checks:
            break
        if prefer_near and near_attempts >= max_near_checks:
            break
        next_due_id = ordered[(position + 1) % len(ordered)][1]

        live_event = live_by_id.get(eid)
        if live_event is not None:
            result = classify_finished_event(row, live_event, checked_at=now)
            if result:
                statuses[eid] = result
                newly_resolved += 1
            else:
                skipped_live += 1
            continue

        # The scheduled time is not proof that play has finished: defer the
        # first near lookup until the likely completion window. If the match
        # was absent or unfinished last time, back off before trying again.
        scheduled = _parse_time(row.get("scheduled_at") or row.get("date"))
        if scheduled is None:
            continue
        if now < scheduled + wait:
            deferred_recent += 1
            continue
        previous_check = _parse_time(last_checked_at.get(eid))
        if previous_check is not None and cooldown and now < previous_check + cooldown:
            deferred_cooldown += 1
            continue

        player_id = _player_id(row, "player1")
        checked += 1
        payload = None
        near_used = False
        try:
            if prefer_near:
                if player_id in near_cache:
                    payload = near_cache[player_id]
                else:
                    if near_attempts >= max_near_checks:
                        checked -= 1
                        break
                    if not callable(near_method):
                        raise RuntimeError("NearStatusRouteUnavailable")
                    near_attempts += 1
                    nominal_requests += 1
                    payload = near_method(player_id)
                    near_cache[player_id] = payload
                near_used = True
            else:
                nominal_requests += 1
                payload = provider.previous_player_matches(player_id, 0)
        except Exception as exc:
            error_code = _provider_error_code(exc)
            provider_errors[error_code] = provider_errors.get(error_code, 0) + 1
            if (
                not prefer_near and error_code.endswith("_HTTP_404")
                and callable(near_method) and near_attempts < max_near_checks
            ):
                # Stop repeating the known 404 route once the documented
                # near-match endpoint succeeds for one real player.
                try:
                    near_attempts += 1
                    nominal_requests += 1
                    payload = near_method(player_id)
                    near_cache[player_id] = payload
                    prefer_near = True
                    near_used = True
                except Exception as fallback_exc:
                    code = _provider_error_code(fallback_exc)
                    provider_errors[code] = provider_errors.get(code, 0) + 1
                    if type(fallback_exc).__name__ == "RequestBudgetExceeded":
                        break
            elif type(exc).__name__ == "RequestBudgetExceeded":
                break

        if payload is None:
            consecutive_errors += 1
            if consecutive_errors >= 3:
                break
            continue

        consecutive_errors = 0
        successful_history += 1
        last_checked_at[eid] = now.isoformat()
        event = next(
            (candidate for candidate in _provider_rows(payload)
             if _provider_event_id(candidate) == eid),
            None,
        )
        if event is None:
            unmatched += 1
            continue
        matched_events += 1
        result = classify_finished_event(row, event, checked_at=now)
        if result:
            statuses[eid] = result
            newly_resolved += 1

    request_count_after = getattr(provider, "request_count", None)
    if isinstance(request_count_before, int) and isinstance(request_count_after, int):
        provider_requests = max(0, request_count_after - request_count_before)
    else:
        provider_requests = nominal_requests

    failed_history = checked - successful_history
    degraded = checked > 0 and successful_history == 0 and failed_history > 0
    # Preserve a successful near-route preference, but never store private
    # provider payloads, player names or error text.
    return {
        "schema": 1,
        "updated_at": now.isoformat(),
        "statuses": statuses,
        "tracked": len(rows),
        "due": len(due),
        "checked": checked,
        "skipped_live": skipped_live,
        "provider_requests": provider_requests,
        "terminal": len(statuses),
        "newly_resolved": newly_resolved,
        "successful_history": successful_history,
        "failed_history": failed_history,
        "matched_events": matched_events,
        "provider_errors": provider_errors,
        "degraded": degraded,
        "preferred_route": "near" if prefer_near else "history",
        "near_attempts": near_attempts,
        "unmatched": unmatched,
        "next_due_id": next_due_id if len(due) > 1 else "",
        "focus_due": focus_due,
        "checkable_now": checkable_now,
        "deferred_recent": deferred_recent,
        "deferred_cooldown": deferred_cooldown,
        "last_checked_at": last_checked_at,
    }
