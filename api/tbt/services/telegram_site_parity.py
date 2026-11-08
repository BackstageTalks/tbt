"""Read-only, worker-authenticated diagnostic projection of web Results.

This is the exact backend Results source BEFORE member-specific entitlement
filtering, NOT a claim that a particular account rendered the same rows.
No provider calls, writes, exclusions changes, or odds reconstruction.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
from typing import Any
from .feed import _row_betting_day
from .result_exclusions import result_bet_id

_SECTIONS = frozenset(("top_daily", "value", "ace"))
_FIELDS = ("correct", "void", "status", "reason", "retirement_line_decided",
           "actual_count", "opponent_actual_count", "profit_units",
           "staked_units", "runtime_source", "ou_readback_regraded")


def site_day_projection(feed: dict, day: str, excluded_ids: set[str] | None = None) -> dict:
    """Extract exact same published bet references consumed by the website.

    Caller must already merge the durable archive, apply read-time settlement
    overlays and *server-side* test exclusions just like api.feed().
    """
    if not isinstance(day, str):
        raise ValueError("day must be string")
    try:
        if datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d") != day:
            raise ValueError("invalid day")
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid day") from exc
    if not isinstance(feed, dict) or not isinstance(feed.get("results"), list):
        raise ValueError("results unavailable")
    if len(feed["results"]) > 25000:
        raise ValueError("results source exceeds audit limit")
    excluded = excluded_ids or set()
    rows: list[dict[str, Any]] = []
    by_section: Counter = Counter()
    hidden: Counter = Counter()
    for source in feed["results"]:
        if not isinstance(source, dict) or _row_betting_day(source) != day:
            continue
        for pub in source.get("market_publications") or []:
            if not isinstance(pub, dict):
                continue
            section = str(pub.get("section") or "").lower()
            if pub.get("publication_status", "published") != "published":
                continue
            if pub.get("excluded_reason") or result_bet_id(source, pub) in excluded:
                hidden[section] += 1
                continue
            result = pub.get("result")
            if not isinstance(result, dict):
                continue
            if (result.get("runtime_source") != "match_status_snapshot"
                    and not pub.get("issued_at")):
                continue
            if type(result.get("correct")) is not bool and result.get("void") is not True:
                continue
            by_section[section] += 1
            if section not in _SECTIONS:
                continue
            rows.append({
                "event_id": str(source.get("event_id") or ""),
                "scheduled_at": str(source.get("scheduled_at") or ""),
                "section": section,
                "market": str(pub.get("market") or ""),
                "selection_id": str(pub.get("selection_id") or pub.get("winner_id") or ""),
                "publication_key": str(pub.get("publication_key") or ""),
                "market_line": pub.get("market_line"),
                "projection_direction": str(pub.get("ou_side") or pub.get("projection_direction") or ""),
                "odds": pub.get("odds"),
                "price_status": pub.get("price_status"),
                "result": {k: deepcopy(result.get(k)) for k in _FIELDS},
            })
    if len(rows) > 1500:
        raise ValueError("scoped site parity rows exceed audit limit")
    return {
        "schema": 1, "betting_day": day,
        "source": "website_results_pre_entitlement_v1",
        "member_render_verified": False, "provider_requests": 0,
        "rows": rows,
        "published_sections": dict(sorted(by_section.items())),
        "excluded_sections": dict(sorted(hidden.items())),
        "raw_feed_results": len(feed["results"]),
        "results_archive_unavailable": bool(feed.get("results_archive_unavailable")),
        "results_exclusions_unavailable": bool(feed.get("results_exclusions_unavailable")),
    }
