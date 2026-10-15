"""Conservative provider-1 market and post-match detail adapters.

Historical TennisApi odds are opening/latest snapshots WITHOUT a quote timestamp.
Nothing emitted here is eligible as an as-of pre-match training price by default.
Point-by-point parsing is intentionally structural until provider point semantics
and complete-match evidence are independently validated.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from ..errors import ProviderError
from .statistics import parse_statistics
from ..services.market_selection import decimal_odds


MARKET_LABELS = {1: "match_winner", 11: "first_set_winner",
                 12: "total_games", 15: "current_set_winner"}


def _check_event(payload: Any, event_id: str | int) -> dict:
    if not isinstance(payload, dict):
        raise ProviderError("TennisApi event details must be an object")
    actual = payload.get("eventId", payload.get("event_id"))
    if actual is not None and str(actual) != str(event_id):
        raise ProviderError("TennisApi event ID differs from requested event")
    return payload


def normalize_market_snapshot(payload: Any, *, event_id: str | int,
                              observed_at: datetime | None = None) -> dict:
    """Only explicit marketIds 1/11/12/15; never infer a missing line.

    observed_at is the time OUR client read the record, not the book's price
    timestamp. Both historical opening and latest are ineligible for backtested
    pre-match CLV/as-of pricing without independent contemporaneous evidence.
    """
    raw = _check_event(payload, event_id)
    when = observed_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    markets = raw.get("markets", [])
    if not isinstance(markets, list):
        raise ProviderError("TennisApi markets must be a list")
    quotes: list[dict] = []
    seen = {}
    for market in markets:
        if not isinstance(market, dict):
            raise ProviderError("Malformed TennisApi market")
        ident = market.get("marketId")
        try:
            market_id = int(ident)
        except (ValueError, TypeError):
            continue
        if market_id not in MARKET_LABELS:
            continue
        live = market.get("isLive", False)
        if not isinstance(live, bool):
            raise ProviderError("TennisApi isLive must be boolean")
        if market_id == 15 and not live:
            continue
        line = None
        if market_id == 12:
            try:
                line = float(market.get("choiceGroup"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(line) or not 0 < line < 150:
                continue
        choices = market.get("choices", [])
        if not isinstance(choices, list):
            raise ProviderError("TennisApi market choices must be a list")
        valid = []
        required = {"Over", "Under"} if market_id == 12 else {"1", "2"}
        for choice in choices:
            if not isinstance(choice, dict):
                raise ProviderError("Malformed TennisApi choice")
            side = str(choice.get("name", "")).strip()
            if side not in required:
                continue
            latest = decimal_odds(choice.get("fractionalValue"))
            opening = decimal_odds(choice.get("initialFractionalValue"))
            if latest is None:
                continue
            winner = choice.get("winning")
            if winner is not None and not isinstance(winner, bool):
                raise ProviderError("Winning indicator must be boolean")
            valid.append({
                "selection": side,
                "opening_decimal": opening,
                "latest_decimal": latest,
                "settled_winning": winner,
            })
        if {v["selection"] for v in valid} != required:
            continue
        for quote in valid:
            row = {
                "market_id": market_id,
                "market": MARKET_LABELS[market_id],
                "is_live": live,
                "line_games": line,
                **quote,
            }
            key = (market_id, live, line, quote["selection"])
            if key in seen:
                if seen[key] != row:
                    raise ProviderError("Conflicting provider-1 selection snapshots")
                continue
            seen[key] = row
            quotes.append(row)
    quotes.sort(key=lambda q: (q["market_id"], q["line_games"] or 0,
                               q["is_live"], q["selection"]))
    return {
        "event_id": str(event_id), "source": "tennisapi1",
        "provider_id": 1, "observed_at_utc": when.astimezone(timezone.utc).isoformat(),
        "provider_quote_timestamp_known": False,
        "pre_match_asof_verified": False,
        "quotes": quotes,
    }


_SET_NUMBER = re.compile(r"^(?:SET\s*)?([1-5])(?:ST|ND|RD|TH)?(?:\s*SET)?$", re.I)
_SHORT_SET = re.compile(r"^S([1-5])$", re.I)


def normalize_set_statistics(payload: Any, *, home_is_player1: bool) -> dict[str, dict]:
    """Reuse verified whole-match parser per separately identified set.

    Unknown/duplicate labels never become pseudo-sets. This intentionally
    excludes live partial-set data unless a caller first verifies match finish.
    """
    if not isinstance(payload, dict):
        raise ProviderError("Invalid statistics envelope")
    periods = payload.get("statistics", [])
    if not isinstance(periods, list):
        raise ProviderError("Invalid statistics periods")
    result: dict[str, dict] = {}
    for period in periods:
        if not isinstance(period, dict):
            continue
        label = str(period.get("period") or "").strip()
        found = _SET_NUMBER.fullmatch(label) or _SHORT_SET.fullmatch(label)
        if not found:
            continue
        number = found.group(1)
        if number in result:
            raise ProviderError("Duplicate set period")
        # Reuse the existing strict field-level statistics contract.
        result[number] = parse_statistics(
            {"statistics": [{**period, "period": "ALL"}]},
            home_is_player1=home_is_player1,
        )
    return result


def normalize_set_statistics_home_away(payload: Any) -> dict[str, dict]:
    """Store stable provider-side labels; canonical p1/p2 order may later swap."""
    sets = normalize_set_statistics(payload, home_is_player1=True)
    return {
        number: {
            ("home_" + key[3:] if key.startswith("p1_") else
             "away_" + key[3:] if key.startswith("p2_") else key): value
            for key, value in values.items()
        }
        for number, values in sets.items()
    }


def point_by_point_inventory(payload: Any, *, event_id: str | int) -> dict:
    """Count provider PBP structure only; do NOT infer point outcomes.

    No PBP statistic is attached to CDB until coverage/completeness, event
    identity, server changes and winner attribution are independently proven.
    """
    # Provider responses may wrap the sets in pointByPoint, return them as
    # a top-level array, or omit the optional feed entirely (204 -> {}).
    # Only recognize known structural containers; do not infer missing points.
    if payload is None:
        sets = []
    elif isinstance(payload, list):
        sets = payload
    else:
        raw = _check_event(payload, event_id)
        container = raw.get("pointByPoint", raw)
        if container is None:
            sets = []
        elif isinstance(container, list):
            sets = container
        elif isinstance(container, dict):
            sets = container.get("sets", [])
        else:
            raise ProviderError("Unsupported point-by-point envelope shape")
    if not isinstance(sets, list) or len(sets) > 5:
        raise ProviderError("Unsupported point-by-point sets shape")
    games_count = points_count = explicit_server_games = explicit_winner_games = 0
    for set_row in sets:
        if not isinstance(set_row, dict):
            raise ProviderError("Invalid point-by-point set")
        if "games" not in set_row:
            raise ProviderError("Unsupported point-by-point set record")
        games = set_row["games"]
        if not isinstance(games, list) or len(games) > 100:
            raise ProviderError("Invalid point-by-point games")
        games_count += len(games)
        for game in games:
            if not isinstance(game, dict):
                raise ProviderError("Invalid point-by-point game")
            if "points" not in game:
                raise ProviderError("Unsupported point-by-point game record")
            points = game["points"]
            if not isinstance(points, list) or len(points) > 300:
                raise ProviderError("Invalid point-by-point points")
            if any(not isinstance(p, dict) for p in points):
                raise ProviderError("Invalid point-by-point point record")
            points_count += len(points)
            score = game.get("score")
            if isinstance(score, dict):
                explicit_server_games += str(score.get("serving")) in {"1", "2"}
                explicit_winner_games += str(score.get("scoring")) in {"1", "2"}
    return {
        "event_id": str(event_id), "source": "tennisapi1",
        "sets": len(sets), "games": games_count, "points": points_count,
        "games_with_explicit_server": explicit_server_games,
        "games_with_explicit_winner": explicit_winner_games,
        "eligible_for_cdb_point_features": False,
        "quality_status": "structural_only" if points_count else "unavailable",
    }
