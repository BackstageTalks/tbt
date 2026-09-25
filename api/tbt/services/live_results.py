"""Independent settlement of actually published LIVE Radar and Set-2 picks.

WATCH alerts and unpublished Set-2 projections never enter this pipeline.
Only verified event IDs, matching player IDs and an observed terminal result
(or a completed second set) may produce a WIN/LOSS/VOID.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .live_comeback import _set_score, _winner
from .match_status import _provider_event_id, _provider_rows, _status_text


def classify_live_signal(item: dict, event: dict) -> dict | None:
    """Classify one published signal from the provider, not from elapsed time."""
    eid = str(item.get("event_id") or "").strip()
    if not eid or eid != _provider_event_id(event):
        return None
    home = event.get("homeTeam") if isinstance(event.get("homeTeam"), dict) else {}
    away = event.get("awayTeam") if isinstance(event.get("awayTeam"), dict) else {}
    hid, aid = str(home.get("id") or ""), str(away.get("id") or "")
    fav, opp = str(item.get("favorite_id") or ""), str(item.get("opponent_id") or "")
    if not fav or not opp or {hid, aid} != {fav, opp} or hid == aid:
        return None
    side = "home" if hid == fav else "away"
    score = []
    for i in range(1, 6):
        pair = _set_score(event, i)
        if None not in pair:
            score.append(f"{pair[0]}:{pair[1]}")
    final_score = " ".join(score)
    set2 = _set_score(event, 2)
    set2_score = f"{set2[0]}:{set2[1]}" if None not in set2 else ""
    raw = _status_text(event)
    voided = any(marker in raw for marker in (
        "retired", "retirement", "retd", "cancelled", "canceled",
        "walkover", "walk over", "abandoned",
    ))
    kind = str(item.get("kind") or "")
    if kind == "set2":
        winner = _winner(set2)
        # Completed set two is settled even if the match is later retired.
        if winner:
            selected_won = (winner == side)
            return {"status": "win" if selected_won else "loss",
                    "second_set": set2_score, "final_score": final_score}
        if voided:
            return {"status": "void", "second_set": set2_score, "final_score": final_score}
        return None
    if kind != "comeback":
        return None
    if voided:
        return {"status": "void", "second_set": set2_score, "final_score": final_score}
    finished = any(word in raw for word in ("finished", "ended", "completed", "full time"))
    try:
        winner_code = int(event.get("winnerCode"))
    except (TypeError, ValueError):
        winner_code = 0
    if not finished or winner_code not in {1, 2}:
        return None
    winner_id = hid if winner_code == 1 else aid
    return {"status": "win" if winner_id == fav else "loss",
            "second_set": set2_score, "final_score": final_score}


def scan_live_signal_results(pending: list[dict], provider: Any, *,
                             now: datetime | None = None, max_checks: int = 30) -> dict:
    """One live response and up to max_checks distinct per-event history lookups.

    The persisted queue is ordered by last attempt; all unfinished signals
    survive feed rollover and get their turn, irrespective of event age.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    timestamp = now.isoformat()
    groups: dict[str, list[dict]] = {}
    for item in pending:
        if not isinstance(item, dict) or item.get("status") != "pending":
            continue
        eid = str(item.get("event_id") or "")
        if eid and item.get("favorite_id") and item.get("opponent_id"):
            groups.setdefault(eid, []).append(item)
    updates: dict[str, dict] = {}
    errors: dict[str, int] = {}
    request_count_before = getattr(provider, "request_count", None)
    nominal_requests = 0
    live: dict[str, dict] = {}
    if groups:
        try:
            nominal_requests += 1
            live = {
                _provider_event_id(event): event
                for event in provider.live_events()
                if isinstance(event, dict) and _provider_event_id(event) in groups
            }
        except Exception as exc:
            name = type(exc).__name__[:64]
            errors[name] = errors.get(name, 0) + 1

    def process(eid: str, event: dict | None) -> None:
        for item in groups[eid]:
            result = classify_live_signal(item, event) if isinstance(event, dict) else None
            updates[str(item["id"])] = {
                "checked_at": timestamp,
                **(result if result is not None else {"status": "pending"}),
            }

    # Free live-feed pass can settle all matching pending signals, including
    # signals past the 30-history-lookup budget.
    for eid, event in live.items():
        process(eid, event)

    checked = successful = unmatched = 0
    max_checks = max(0, min(60, int(max_checks)))
    for eid, items in groups.items():
        if eid in live or checked >= max_checks:
            continue
        player_id = str(items[0]["favorite_id"])
        checked += 1
        nominal_requests += 1
        try:
            method = getattr(provider, "near_player_matches_for_status", None)
            if not callable(method):
                method = getattr(provider, "previous_player_matches")
                data = method(player_id, 0)
            else:
                data = method(player_id)
            successful += 1
            event = next(
                (row for row in _provider_rows(data) if _provider_event_id(row) == eid),
                None,
            )
            if event is None:
                unmatched += 1
            process(eid, event)
        except Exception as exc:
            name = type(exc).__name__[:64]
            errors[name] = errors.get(name, 0) + 1
            process(eid, None)
            # One broken endpoint must not burn all remaining quota.
            if sum(errors.values()) >= 3:
                break
    request_count_after = getattr(provider, "request_count", None)
    actual_requests = (
        max(0, request_count_after - request_count_before)
        if isinstance(request_count_before, int) and isinstance(request_count_after, int)
        else nominal_requests
    )
    terminal = sum(x["status"] != "pending" for x in updates.values())
    return {
        "scanned_at": timestamp,
        "pending_events": len(groups),
        "pending_signals": sum(map(len, groups.values())),
        "checked": checked,
        "live_matched": len(live),
        "successful_history": successful,
        "unmatched": unmatched,
        "newly_resolved": terminal,
        "provider_requests": actual_requests,
        "provider_errors": errors,
        "degraded": bool(groups and checked and not successful and not live and errors),
        "updates": updates,
    }
