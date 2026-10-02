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

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
import time
from typing import Any
from zoneinfo import ZoneInfo


TERMINAL_STATUSES = {"win", "loss", "retired", "void"}

_PUBLIC_MATCH_WINNER_KEYS = (
    "top200_picks",
    "prime_picks",
    "top_daily_picks",
    "value_picks",
    "doubles_picks",
)
LEGACY_PENDING_CARRY_HOURS = 48


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
    """Return published Match Winner rows that need runtime settlement."""
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

    public_contract_present = any(key in feed for key in _PUBLIC_MATCH_WINNER_KEYS)
    if public_contract_present:
        for key in _PUBLIC_MATCH_WINNER_KEYS:
            add_rows(feed.get(key))
    else:
        # Compatibility fallback for focused tests/legacy payloads that predate
        # the public market-section contract. Production feeds carry the public
        # keys above, so generic model-board rows are never queued there.
        add_rows(feed.get("upcoming"))

    return out


def event_ids_from_feed(feed: dict[str, Any]) -> set[str]:
    return set(prediction_rows(feed))


_RUNTIME_RESULT_SOURCE_KEYS = (
    "top200_picks",
    "daily_picks",
    "prime_picks",
    "top_daily_picks",
    "value_picks",
    "doubles_picks",
)


def _runtime_publication_key(
    row: dict[str, Any], publication: dict[str, Any], index: int = 0
) -> str:
    event_id = _event_id(row)
    section = str(publication.get("section") or "").strip().lower()
    market = str(publication.get("market") or "match_winner").strip().lower()
    selection = str(
        publication.get("selection_id")
        or publication.get("winner_id")
        or publication.get("pick_id")
        or ""
    ).strip()
    issued_at = str(publication.get("issued_at") or "").strip()
    if event_id and selection and issued_at:
        return f"{event_id}|{section}|{market}|{selection}|{issued_at}"
    return f"{event_id}|{section}|{market}|{selection}|{issued_at}|{index}"


def runtime_settled_results(
    feed: dict[str, Any], statuses: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Overlay verified match-winner settlements onto an already-authorized feed.

    The durable prediction ledger and deployed feed remain immutable. This helper
    only builds response-time Results rows from the external match-status snapshot,
    and only for issued match-winner publications visible to this account.
    Projection markets (ACES/DF/Games/Sets) are intentionally never settled from
    a match-winner outcome.
    """
    existing_results = [
        deepcopy(row) for row in (feed.get("results") or []) if isinstance(row, dict)
    ]
    if not isinstance(statuses, dict) or not statuses:
        return existing_results

    seen: set[str] = set()
    for row in existing_results:
        for index, publication in enumerate(row.get("market_publications") or []):
            if isinstance(publication, dict):
                seen.add(_runtime_publication_key(row, publication, index))

    runtime_rows: list[dict[str, Any]] = []
    runtime_seen: set[str] = set()
    for source_key in _RUNTIME_RESULT_SOURCE_KEYS:
        rows = feed.get(source_key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            event_id = _event_id(row)
            status_row = statuses.get(event_id)
            if not isinstance(status_row, dict):
                continue
            status = str(status_row.get("status") or "").strip().lower()
            if status not in TERMINAL_STATUSES:
                continue

            expected_selection = _selection_id(row)
            overlay_publications: list[dict[str, Any]] = []
            for index, publication in enumerate(row.get("market_publications") or []):
                if not isinstance(publication, dict):
                    continue
                if not publication.get("issued_at") or publication.get("excluded_reason"):
                    continue
                section = str(publication.get("section") or "").strip().lower()
                market = str(publication.get("market") or "").strip().lower()
                if not market and section in {"top200", "top_daily", "prime", "value", "doubles"}:
                    market = "match_winner"
                if market != "match_winner":
                    continue
                publication_status = str(
                    publication.get("publication_status") or "published"
                ).strip().lower()
                if publication_status != "published":
                    continue
                selection = str(
                    publication.get("selection_id")
                    or publication.get("winner_id")
                    or publication.get("pick_id")
                    or ""
                ).strip()
                if expected_selection and selection and selection != expected_selection:
                    continue

                key = _runtime_publication_key(row, publication, index)
                if key in seen or key in runtime_seen:
                    continue

                result = publication.get("result")
                result = deepcopy(result) if isinstance(result, dict) else {}
                checked_at = str(status_row.get("checked_at") or "").strip()
                scheduled_at = str(row.get("scheduled_at") or row.get("date") or "").strip()
                odds_raw = publication.get("odds")
                try:
                    odds = float(odds_raw)
                except (TypeError, ValueError):
                    odds = 0.0

                if status in {"retired", "void"}:
                    result.update({
                        "status": "retired" if status == "retired" else "void",
                        "correct": None,
                        "void": True,
                        "reason": "retired" if status == "retired" else (
                            str(status_row.get("provider_status") or "void")[:120]
                        ),
                        "staked_units": 0.0,
                        "return_units": 0.0,
                        "profit_units": 0.0,
                    })
                else:
                    correct = status == "win"
                    result.update({
                        "status": "hit" if correct else "miss",
                        "correct": correct,
                    })
                    # A live status can settle W/L without odds, but financial
                    # fields are created only when the issued publication has a
                    # genuine price. This keeps ROI fail-closed.
                    if odds > 1:
                        result.update({
                            "staked_units": 1.0,
                            "return_units": odds if correct else 0.0,
                            "profit_units": (odds - 1.0) if correct else -1.0,
                        })
                result.update({
                    "settled_at": checked_at or scheduled_at,
                    "scheduled_at": scheduled_at,
                    "runtime_overlay": True,
                    "runtime_source": "match_status_snapshot",
                })
                copy = deepcopy(publication)
                copy["result"] = result
                overlay_publications.append(copy)
                runtime_seen.add(key)

            if overlay_publications:
                copy = deepcopy(row)
                copy["market_publications"] = overlay_publications
                copy["runtime_result_overlay"] = True
                runtime_rows.append(copy)

    combined = existing_results + runtime_rows
    combined.sort(
        key=lambda row: _parse_time(row.get("scheduled_at") or row.get("date"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return combined


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
    void = any(marker in status_text for marker in (
        "cancelled", "canceled", "walkover", "walk over", "w/o",
    ))

    winner_code = event.get("winnerCode")
    try:
        winner_code = int(winner_code)
    except (TypeError, ValueError):
        winner_code = 0

    finished = any(
        marker in status_text
        for marker in ("finished", "ended", "completed", "full time")
    ) or winner_code in {1, 2}

    if not finished and not retired and not void:
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
    if void:
        return {**base, "status": "void"}

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


def _second_set_outcome(row: dict[str, Any], event: dict[str, Any]) -> str:
    """Return win/loss for the predicted player once set 2 is complete."""
    home_score = event.get("homeScore") if isinstance(event.get("homeScore"), dict) else {}
    away_score = event.get("awayScore") if isinstance(event.get("awayScore"), dict) else {}
    try:
        home = int(home_score.get("period2"))
        away = int(away_score.get("period2"))
    except (TypeError, ValueError):
        return ""
    hi, lo = max(home, away), min(home, away)
    if not ((hi == 6 and lo <= 4) or (hi == 7 and lo in {5, 6})):
        return ""
    home_team = event.get("homeTeam") if isinstance(event.get("homeTeam"), dict) else {}
    away_team = event.get("awayTeam") if isinstance(event.get("awayTeam"), dict) else {}
    home_id = str(home_team.get("id") or "").strip()
    away_id = str(away_team.get("id") or "").strip()
    predicted = _selection_id(row)
    if not predicted or predicted not in {home_id, away_id}:
        return ""
    set_winner = home_id if home > away else away_id
    return "win" if predicted == set_winner else "loss"


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
    max_near_checks: int = 30,
    max_wall_seconds: float | None = None,
) -> dict[str, Any]:
    """Settle verified events without trusting a consistently 404ing history route.

    TennisApi's /player/{id}/events/near is an alternate compact source for
    the closest previous/next match. It is NOT guaranteed to contain every
    historical match, so a missing event is left pending, never scored.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    # Stop before the Azure HTTP gateway deadline; defer, never discard, unfinished rows.
    deadline = (time.monotonic() + max(0.0, max_wall_seconds)
                if max_wall_seconds is not None else None)
    time_budget_exhausted = False
    rows = prediction_rows(feed)
    prior = previous_snapshot if isinstance(previous_snapshot, dict) else {}
    prior_pending = prior.get("pending")
    prior_pending = prior_pending if isinstance(prior_pending, dict) else {}

    # Carry only pending rows that were created by the public-pick worker.
    # Legacy snapshots used to include the entire model/board feed, which created
    # a large stale backlog unrelated to published bets. Unmarked legacy rows are
    # intentionally dropped. Marked public picks may survive a feed rollover for
    # up to 48 hours so yesterday's late/unfinished matches can still settle.
    carry_cutoff = now - timedelta(hours=LEGACY_PENDING_CARRY_HOURS)
    for eid, saved in prior_pending.items():
        if eid in rows or not isinstance(saved, dict):
            continue
        scheduled = _parse_time(saved.get("t"))
        if (
            str(saved.get("p") or "") != "1"
            or scheduled is None
            or scheduled < carry_cutoff
            or not (saved.get("s") and saved.get("a") and saved.get("b"))
        ):
            continue
        rows[eid] = {
            "event_id": eid, "scheduled_at": saved["t"], "winner_id": saved["s"],
            "player1": {"id": saved["a"]}, "player2": {"id": saved["b"]},
        }

    existing = prior.get("statuses")
    existing = existing if isinstance(existing, dict) else {}
    statuses: dict[str, dict[str, Any]] = {
        str(eid): dict(value)
        for eid, value in existing.items()
        if isinstance(value, dict)
        and str(value.get("status") or "") in TERMINAL_STATUSES
    }

    due: list[tuple[datetime, str, dict[str, Any]]] = []
    pending: dict[str, dict[str, str]] = {}
    for eid, row in rows.items():
        if eid in statuses:
            continue
        scheduled = _parse_time(row.get("scheduled_at") or row.get("date"))
        player1 = _player_id(row, "player1")
        player2 = _player_id(row, "player2")
        selection = _selection_id(row)
        if scheduled is None or not (player1 and player2 and selection):
            continue
        old = prior_pending.get(eid)
        old = old if isinstance(old, dict) else {}
        compact = {
            "t": scheduled.isoformat(), "s": selection,
            "a": player1, "b": player2, "c": str(old.get("c") or "")[:64],
            "p": "1",
        }
        # Keep postponed fixtures in the queue, without querying future starts.
        if eid in prior_pending:
            pending[eid] = compact
        if scheduled >= now:
            continue
        due.append((scheduled, eid, row))
        pending[eid] = compact

    # Preserve the full backlog, but under severe backlog pressure prioritize
    # the current Bratislava betting day (06:00–06:00) without increasing the
    # provider-request budget. At least one history slot remains available for
    # older pending fixtures so the backlog still drains.
    due.sort(key=lambda item: (item[0], item[1]))
    priority_limit = max(0, min(120, int(max_checks)))
    local_now = now.astimezone(ZoneInfo("Europe/Bratislava"))
    betting_day_start_local = local_now.replace(hour=6, minute=0, second=0, microsecond=0)
    if local_now < betting_day_start_local:
        betting_day_start_local -= timedelta(days=1)
    betting_day_start = betting_day_start_local.astimezone(timezone.utc)
    recent_due = [item for item in due if item[0] >= betting_day_start]
    backlog_due = [item for item in due if item[0] < betting_day_start]
    priority_mode = bool(
        recent_due and backlog_due and priority_limit >= 2
        and len(due) > max(40, priority_limit * 20)
    )

    def fairness_key(item: tuple[datetime, str, dict[str, Any]]):
        _, eid, _ = item
        old = prior_pending.get(eid)
        old = old if isinstance(old, dict) else {}
        last_checked = _parse_time(old.get("c"))
        return (
            last_checked or datetime.min.replace(tzinfo=timezone.utc),
            item[0],
            eid,
        )

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
    budget_paused = False
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
            if type(exc).__name__ == "SharedBudgetExhausted":
                # The shared daily quota guard stopped the call before it reached
                # the tennis provider. Preserve every pending fixture and exit
                # cleanly instead of retrying the same exhausted reservation.
                budget_paused = True

    checked = skipped_live = successful_history = matched_events = 0
    newly_resolved = consecutive_errors = near_attempts = unmatched = 0
    next_due_id = ""
    settled_events: dict[str, dict[str, str]] = {}
    max_checks = priority_limit
    cursor = str(prior.get("next_due_id") or "")
    if priority_mode:
        recent_ordered = sorted(recent_due, key=fairness_key)
        backlog_ordered = sorted(backlog_due, key=fairness_key)
        recent_quota = min(len(recent_ordered), max(1, max_checks - 1))
        backlog_quota = min(len(backlog_ordered), max_checks - recent_quota)
        # If the current day has fewer candidates than the request budget,
        # give the unused slots back to the backlog.
        if recent_quota + backlog_quota < max_checks:
            backlog_quota = min(
                len(backlog_ordered), max_checks - recent_quota
            )
        ordered = (
            recent_ordered[:recent_quota]
            + backlog_ordered[:backlog_quota]
            + recent_ordered[recent_quota:]
            + backlog_ordered[backlog_quota:]
        )
    else:
        offset = next((i for i, (_, eid, _) in enumerate(due) if eid == cursor), 0)
        ordered = due[offset:] + due[:offset]

    # One live request can settle every due fixture, including those beyond
    # the per-event request budget of thirty.
    for _, eid, row in due:
        live_event = live_by_id.get(eid)
        if live_event is None:
            continue
        result = classify_finished_event(row, live_event, checked_at=now)
        if result:
            statuses[eid] = result
            pending.pop(eid, None)
            newly_resolved += 1
            settled_events[eid] = {
                "event_id": eid,
                "match_status": str(result.get("status") or ""),
                "second_set_status": _second_set_outcome(row, live_event),
                "checked_at": now.isoformat(),
            }
        else:
            skipped_live += 1

    runtime_limited = False
    if budget_paused and ordered:
        next_due_id = ordered[0][1]
    for position, (_, eid, row) in enumerate(ordered):
        if budget_paused:
            break
        if eid in statuses or eid in live_by_id:
            continue
        if deadline is not None and time.monotonic() >= deadline:
            runtime_limited = True
            time_budget_exhausted = True
            next_due_id = eid
            break
        if checked >= max_checks:
            next_due_id = eid
            break
        if prefer_near and near_attempts >= max_near_checks:
            next_due_id = eid
            break
        # Leave time for one provider call and durable snapshot persistence.
        if deadline is not None and time.monotonic() + 5.0 >= deadline:
            runtime_limited = True
            time_budget_exhausted = True
            next_due_id = eid
            break
        next_due_id = ordered[(position + 1) % len(ordered)][1]

        player_id = _player_id(row, "player1")
        checked += 1
        previous_checked_at = ""
        if eid in pending:
            previous_checked_at = str(pending[eid].get("c") or "")
            pending[eid]["c"] = now.isoformat()
        payload = None
        near_used = False
        try:
            if prefer_near:
                if player_id in near_cache:
                    payload = near_cache[player_id]
                else:
                    if near_attempts >= max_near_checks:
                        checked -= 1
                        next_due_id = eid
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
            if type(exc).__name__ == "SharedBudgetExhausted":
                budget_paused = True
                checked = max(0, checked - 1)
                if eid in pending:
                    pending[eid]["c"] = previous_checked_at
                next_due_id = eid
                break
            if (
                not prefer_near and error_code.endswith("_HTTP_404")
                and callable(near_method) and near_attempts < max_near_checks
            ):
                # Do not start a second slow provider call near the deadline.
                if deadline is not None and time.monotonic() + 5.0 >= deadline:
                    runtime_limited = True
                    time_budget_exhausted = True
                    next_due_id = eid
                    break
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
                    if type(fallback_exc).__name__ == "SharedBudgetExhausted":
                        budget_paused = True
                        checked = max(0, checked - 1)
                        if eid in pending:
                            pending[eid]["c"] = previous_checked_at
                        next_due_id = eid
                        break
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
            pending.pop(eid, None)
            newly_resolved += 1
            settled_events[eid] = {
                "event_id": eid,
                "match_status": str(result.get("status") or ""),
                "second_set_status": _second_set_outcome(row, event),
                "checked_at": now.isoformat(),
            }

    request_count_after = getattr(provider, "request_count", None)
    if isinstance(request_count_before, int) and isinstance(request_count_after, int):
        provider_requests = max(0, request_count_after - request_count_before)
    else:
        provider_requests = nominal_requests

    failed_history = checked - successful_history
    degraded = (
        checked > 0 and successful_history == 0 and failed_history > 0
        and not budget_paused
    )
    # Preserve a successful near-route preference, but never store private
    # provider payloads, player names or error text.
    return {
        "schema": 1,
        "updated_at": now.isoformat(),
        "statuses": statuses,
        "tracked": len(rows),
        "due": len(due),
        "window_candidates": len(due),  # Legacy diagnostic, no window cutoff.
        "window_min_age_minutes": 0,
        "window_max_age_minutes": 0,
        "priority_mode": priority_mode,
        "betting_day_start": betting_day_start.isoformat(),
        "current_betting_day_due": len(recent_due),
        "backlog_due": len(backlog_due),
        "pending_count": len(pending),
        "pending": pending,
        "checked": checked,
        "skipped_live": skipped_live,
        "provider_requests": provider_requests,
        "time_budget_exhausted": time_budget_exhausted,
        "terminal": len(statuses),
        "newly_resolved": newly_resolved,
        "successful_history": successful_history,
        "failed_history": failed_history,
        "matched_events": matched_events,
        "provider_errors": provider_errors,
        "budget_paused": budget_paused,
        "degraded": degraded,
        "preferred_route": "near" if prefer_near else "history",
        "near_attempts": near_attempts,
        "unmatched": unmatched,
        "next_due_id": next_due_id if len(due) > 1 else "",
        "runtime_limited": runtime_limited,
        "settled_events": list(settled_events.values()),
    }
