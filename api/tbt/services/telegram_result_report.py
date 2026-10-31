"""Read-only Telegram results view of the existing official BlinQ Results.

Never settles matches, fetches provider data, or changes prediction/CDB state.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .dashboard_kpis import _result_outcome
from .result_exclusions import apply_result_exclusions, result_bet_id
from .results_archive import merge_settled_results

_ZONE = ZoneInfo("Europe/Bratislava")
_SECTIONS = {"top_daily": "top", "value": "value", "ace": "aces"}


def betting_day(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("Results must have timezone-aware times")
    local = moment.astimezone(_ZONE)
    if local.hour < 6:
        local -= timedelta(days=1)
    return local.date().isoformat()


def previous_closed_day(now: datetime) -> str:
    local = now.astimezone(_ZONE)
    if local.hour < 6:
        raise ValueError("Previous betting day has not closed")
    return (date.fromisoformat(betting_day(now)) - timedelta(days=1)).isoformat()


def _timestamp(value):
    try:
        result = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _priced(pub, result):
    """Only an issued, real quoted 1u wager may affect ROI."""
    try:
        quote = float(pub.get("odds"))
        stake = float(result.get("staked_units"))
        profit = float(result.get("profit_units"))
    except (TypeError, ValueError):
        return None, None
    import math
    if not all(map(math.isfinite, (quote, stake, profit))):
        return None, None
    if quote <= 1 or stake <= 0:
        return None, None
    market = str(pub.get("market") or "").lower()
    price = str(pub.get("price_status") or "").lower()
    if market in {"aces", "double_faults", "sets", "games"}:
        if price != "priced_projection":
            return None, None
    elif price not in ("", "priced", "priced_projection"):
        return None, None
    return stake, profit


def _selection(row, pub):
    target = str(pub.get("selection_id") or pub.get("winner_id") or "").strip()
    for key in ("player1", "player2"):
        player = row.get(key) if isinstance(row.get(key), dict) else {}
        if str(player.get("id") or "") == target and player.get("name"):
            return str(player["name"])
    return str(pub.get("selection") or pub.get("pick") or target).strip()


def report_rows(feed: dict, archive: list, exclusions: set, target_day: str) -> dict:
    """Deduplicate official published outcomes; retain only previous-day records."""
    date.fromisoformat(target_day)
    base = merge_settled_results(feed, archive)
    result_feed = apply_result_exclusions(base, exclusions)
    seen = {}
    for row in result_feed.get("results") or []:
        if not isinstance(row, dict):
            continue
        scheduled = _timestamp(row.get("scheduled_at") or row.get("date"))
        if scheduled is None or betting_day(scheduled) != target_day:
            continue
        raw_day = str(row.get("betting_day") or "").strip()
        if raw_day and raw_day != target_day:
            continue
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict) or pub.get("excluded_reason"):
                continue
            section = str(pub.get("section") or "").lower()
            market = str(pub.get("market") or "").lower()
            if section not in _SECTIONS or (section == "ace" and market != "aces"):
                continue
            if section in {"top_daily", "value"} and market not in ("", "match_winner"):
                continue
            pub_day = str(pub.get("betting_day") or (pub.get("issued_snapshot") or {}).get("betting_day") or "").strip()
            if pub_day and pub_day != target_day:
                continue
            result = pub.get("result") if isinstance(pub.get("result"), dict) else {}
            if not pub.get("issued_at") and result.get("runtime_source") != "match_status_snapshot":
                continue
            issued = _timestamp(pub.get("issued_at"))
            if pub.get("issued_at") and (issued is None or issued > scheduled):
                continue
            outcome = _result_outcome(pub)
            if outcome == "pending" and not pub.get("issued_at"):
                continue
            identity = result_bet_id(row, pub)
            if not identity:
                continue
            stake, profit = _priced(pub, result) if outcome in ("win", "loss") else (None, None)
            item = {
                "id": identity, "section": _SECTIONS[section],
                "event_id": str(row.get("event_id") or row.get("id") or ""),
                "scheduled_at": scheduled.isoformat(),
                "selection": _selection(row, pub),
                "status": outcome,
                "odds": pub.get("odds") if stake is not None else None,
                "stake": stake, "profit": profit,
            }
            existing = seen.get(identity)
            # VALUE has display priority over TOP if a legacy duplicate slipped through.
            # A verified terminal result has priority over an earlier pending copy.
            if existing is None or (
                (item["status"] != "pending" and existing["status"] == "pending")
                or (item["section"] == "value" and existing["section"] == "top")
            ):
                seen[identity] = item
    rows = sorted(seen.values(), key=lambda x: (x["section"], x["scheduled_at"], x["id"]))
    settled = sum(x["status"] != "pending" for x in rows)
    return {
        "schema": 1, "betting_day": target_day,
        "source": "blinq_issued_results_archive_read_only",
        "coverage": "recorded_results_only",
        "settled": settled, "pending_known": len(rows) - settled,
        "rows": rows,
    }
