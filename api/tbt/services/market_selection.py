"""Odds-backed current-market selection for BlinQ dashboard sections.

This module never creates a new model probability. It only combines already
published Match Winner probabilities with a current provider-1 odds snapshot.
Aces/DF and Sets/Games remain separate model outputs and are intentionally not
fabricated here.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import re
from typing import Any, Iterable
from zoneinfo import ZoneInfo


MATCH_WINNER_MARKET_NAMES = {
    "full time",
    "fulltime",
    "match winner",
    "matchwinner",
    "winner",
    "moneyline",
}


def _normal(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().replace("_", " ").split())


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def decimal_odds(value: Any) -> float | None:
    """Convert provider odds representations to decimal odds conservatively."""
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip()
        fraction = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)", text)
        if fraction:
            numerator, denominator = map(float, fraction.groups())
            if denominator <= 0:
                return None
            result = 1.0 + numerator / denominator
            return result if 1.01 <= result <= 1000 else None
    number = _number(value)
    if number is None:
        return None
    # TennisApi's *FractionalValue fields may be exposed as already-decimal
    # numbers in some wrappers. Values <= 1 cannot be safe decimal prices.
    return number if 1.01 <= number <= 1000 else None


def _walk_market_rows(value: Any, inherited_market: str = "") -> Iterable[tuple[dict[str, Any], str]]:
    if isinstance(value, list):
        for item in value:
            yield from _walk_market_rows(item, inherited_market)
        return
    if not isinstance(value, dict):
        return

    market = str(
        value.get("marketName")
        or value.get("market_name")
        or value.get("market")
        or inherited_market
        or ""
    ).strip()

    # Yield dicts that can plausibly be a priced outcome.
    if any(
        key in value
        for key in (
            "fractionalValue", "currentFractionalValue", "odds", "price",
            "decimalOdds", "decimal_odds", "value",
        )
    ):
        yield value, market

    for key, child in value.items():
        if key in {
            "marketName", "market_name", "market", "fractionalValue",
            "currentFractionalValue", "initialFractionalValue", "odds", "price",
            "decimalOdds", "decimal_odds", "value",
        }:
            continue
        if isinstance(child, (dict, list)):
            yield from _walk_market_rows(child, market)


def _is_match_winner_market(name: str) -> bool:
    normalized = _normal(name)
    compact = normalized.replace(" ", "")
    if "first set" in normalized or "set winner" in normalized or "tie break" in normalized:
        return False
    return normalized in MATCH_WINNER_MARKET_NAMES or compact in {x.replace(" ", "") for x in MATCH_WINNER_MARKET_NAMES}


def _outcome_text(row: dict[str, Any]) -> str:
    for key in (
        "choiceName", "choice_name", "outcomeName", "outcome_name", "label",
        "name", "choice", "outcome", "selection", "participantName", "teamName",
    ):
        value = row.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("label") or value.get("shortName")
        if value not in (None, ""):
            return str(value).strip()
    for key in ("team", "player", "participant"):
        value = row.get(key)
        if isinstance(value, dict):
            name = value.get("name") or value.get("shortName")
            if name:
                return str(name).strip()
    return ""


def _price(row: dict[str, Any]) -> float | None:
    for key in (
        "fractionalValue", "currentFractionalValue", "decimalOdds",
        "decimal_odds", "odds", "price", "value",
    ):
        value = decimal_odds(row.get(key))
        if value is not None:
            return value
    return None


def _opening_price(row: dict[str, Any]) -> float | None:
    for key in ("initialFractionalValue", "openingOdds", "opening_odds"):
        value = decimal_odds(row.get(key))
        if value is not None:
            return value
    return None


def _match_side(label: str, player1: str, player2: str) -> int | None:
    text = _normal(label)
    if not text:
        return None
    p1 = _normal(player1)
    p2 = _normal(player2)
    aliases1 = {"1", "home", "home team", "player 1", "player1", p1}
    aliases2 = {"2", "away", "away team", "player 2", "player2", p2}
    if text in aliases1 or (p1 and (text == p1 or p1 in text or text in p1)):
        return 1
    if text in aliases2 or (p2 and (text == p2 or p2 in text or text in p2)):
        return 2
    return None


def extract_match_winner_odds(payload: Any, player1_name: str, player2_name: str) -> dict[str, Any] | None:
    """Extract a two-way Full time / Match Winner market from provider payload."""
    prices: dict[int, dict[str, Any]] = {}
    for row, market_name in _walk_market_rows(payload):
        if not _is_match_winner_market(market_name):
            continue
        price = _price(row)
        if price is None:
            continue
        side = _match_side(_outcome_text(row), player1_name, player2_name)
        if side is None:
            # Some provider shapes expose explicit home/away selector fields.
            selector = row.get("choiceCode") or row.get("outcomeCode") or row.get("type")
            side = _match_side(str(selector or ""), player1_name, player2_name)
        if side is None:
            continue
        # Prefer the first complete current price. Duplicate rows are not merged
        # across providers because this enrichment intentionally uses provider 1.
        prices.setdefault(
            side,
            {
                "odds": price,
                "opening_odds": _opening_price(row),
                "change": row.get("change"),
                "source_id": row.get("sourceId") or row.get("source_id"),
            },
        )

    if 1 not in prices or 2 not in prices:
        return None
    o1, o2 = prices[1]["odds"], prices[2]["odds"]
    raw1, raw2 = 1.0 / o1, 1.0 / o2
    total = raw1 + raw2
    if not math.isfinite(total) or total <= 0:
        return None
    return {
        "player1_odds": o1,
        "player2_odds": o2,
        "player1_opening_odds": prices[1].get("opening_odds"),
        "player2_opening_odds": prices[2].get("opening_odds"),
        "player1_implied_probability": raw1 / total,
        "player2_implied_probability": raw2 / total,
        "raw_overround": total - 1.0,
        "player1_change": prices[1].get("change"),
        "player2_change": prices[2].get("change"),
        "source_id": prices[1].get("source_id") or prices[2].get("source_id"),
    }


def betting_day_bounds(
    now: datetime,
    *,
    timezone_name: str = "Europe/Bratislava",
    start_hour: int = 6,
) -> tuple[datetime, datetime, str]:
    if now.tzinfo is None:
        raise ValueError("betting_day_bounds requires timezone-aware now")
    if not 0 <= int(start_hour) <= 23:
        raise ValueError("start_hour must be 0..23")
    zone = ZoneInfo(timezone_name)
    local = now.astimezone(zone)
    start = local.replace(hour=int(start_hour), minute=0, second=0, microsecond=0)
    if local < start:
        start -= timedelta(days=1)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc), start.date().isoformat()


def _prediction_time(row: dict[str, Any]) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(row.get("scheduled_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc)


def _depth(row: dict[str, Any]) -> float:
    value = _number(row.get("data_depth"))
    if value is None:
        return 0.0
    return max(0.0, min(1.0, value))


def _confidence(row: dict[str, Any]) -> float:
    value = _number(row.get("confidence"))
    if value is not None and 0 < value < 1:
        return value
    players = [row.get("player1") or {}, row.get("player2") or {}]
    probabilities = [_number(player.get("probability")) for player in players if isinstance(player, dict)]
    probabilities = [value for value in probabilities if value is not None]
    return max(probabilities) if probabilities else 0.0


def attach_match_winner_market(
    row: dict[str, Any],
    market: dict[str, Any],
    *,
    captured_at: datetime,
    provider_id: int = 1,
    betting_day: str | None = None,
) -> dict[str, Any]:
    result = deepcopy(row)
    p1 = result.get("player1") if isinstance(result.get("player1"), dict) else {}
    p2 = result.get("player2") if isinstance(result.get("player2"), dict) else {}
    winner_id = str(result.get("winner_id") or "")
    p1_id, p2_id = str(p1.get("id") or ""), str(p2.get("id") or "")
    if winner_id == p1_id:
        model_probability = _number(p1.get("probability")) or 0.0
        odds = market["player1_odds"]
        implied = market["player1_implied_probability"]
        selection = p1.get("name") or "Player 1"
    elif winner_id == p2_id:
        model_probability = _number(p2.get("probability")) or 0.0
        odds = market["player2_odds"]
        implied = market["player2_implied_probability"]
        selection = p2.get("name") or "Player 2"
    else:
        return result

    edge = model_probability - implied
    expected_value = model_probability * odds - 1.0
    result["match_winner_market"] = {
        **market,
        "provider_id": int(provider_id),
        "source": "tennisapi_provider_1",
        "captured_at": captured_at.astimezone(timezone.utc).isoformat(),
        "betting_day": betting_day,
    }
    result["betting"] = {
        "market": "match_winner",
        "selection": selection,
        "selection_id": winner_id,
        "odds": odds,
        "fair_implied_probability": implied,
        "model_probability": model_probability,
        "edge": edge,
        "expected_value": expected_value,
        "provider_id": int(provider_id),
        "captured_at": captured_at.astimezone(timezone.utc).isoformat(),
        "betting_day": betting_day,
    }
    return result


def enrich_current_betting_day_odds(
    provider: Any,
    predictions: list[dict[str, Any]],
    *,
    now: datetime,
    max_events: int = 150,
    provider_id: int = 1,
    timezone_name: str = "Europe/Bratislava",
    start_hour: int = 6,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch provider-1 odds only for the current BlinQ betting day."""
    start, end, day_key = betting_day_bounds(
        now, timezone_name=timezone_name, start_hour=start_hour
    )
    indexed = {str(row.get("event_id") or ""): deepcopy(row) for row in predictions}
    candidates = []
    for row in indexed.values():
        scheduled = _prediction_time(row)
        if scheduled is None or not start <= scheduled < end:
            continue
        candidates.append(row)
    # Spend scarce odds calls on the strongest/data-richest predictions first.
    candidates.sort(key=lambda row: (_confidence(row), _depth(row)), reverse=True)
    if max_events > 0:
        candidates = candidates[:max_events]

    report = {
        "betting_day": day_key,
        "timezone": timezone_name,
        "start_hour": int(start_hour),
        "candidates": len(candidates),
        "odds_requested": 0,
        "odds_available": 0,
        "odds_unavailable": 0,
        "errors": 0,
        "provider_id": int(provider_id),
    }
    for row in candidates:
        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            continue
        p1 = row.get("player1") if isinstance(row.get("player1"), dict) else {}
        p2 = row.get("player2") if isinstance(row.get("player2"), dict) else {}
        try:
            report["odds_requested"] += 1
            payload = provider.event_odds(event_id, provider_id=provider_id)
            market = extract_match_winner_odds(
                payload,
                str(p1.get("name") or ""),
                str(p2.get("name") or ""),
            )
        except Exception:
            report["errors"] += 1
            continue
        if market is None:
            report["odds_unavailable"] += 1
            continue
        report["odds_available"] += 1
        indexed[event_id] = attach_match_winner_market(
            row,
            market,
            captured_at=now,
            provider_id=provider_id,
            betting_day=day_key,
        )

    enriched = [indexed.get(str(row.get("event_id") or ""), deepcopy(row)) for row in predictions]
    report["coverage"] = (
        report["odds_available"] / report["odds_requested"]
        if report["odds_requested"] else 0.0
    )
    return enriched, report


def _market_card(row: dict[str, Any]) -> dict[str, Any] | None:
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    if betting.get("market") != "match_winner":
        return None
    card = deepcopy(row)
    card["market"] = "match_winner"
    card["market_type"] = "Match Winner"
    card["pick"] = betting.get("selection")
    card["selection"] = betting.get("selection")
    card["odds"] = betting.get("odds")
    card["edge"] = betting.get("edge")
    card["expected_value"] = betting.get("expected_value")
    card["probability"] = betting.get("model_probability")
    card["fair_implied_probability"] = betting.get("fair_implied_probability")
    card["betting_day"] = betting.get("betting_day")
    return card


def select_market_sections(
    predictions: list[dict[str, Any]],
    *,
    top_daily_limit: int = 10,
    top_daily_min_probability: float = 0.60,
    top_daily_min_edge: float = 0.0,
    top_daily_min_data_depth: float = 0.30,
    value_min_odds: float = 1.70,
    value_max_implied_gap: float = 0.15,
) -> dict[str, Any]:
    cards = [card for row in predictions if (card := _market_card(row)) is not None]

    daily = [
        card for card in cards
        if (_number(card.get("probability")) or 0.0) >= top_daily_min_probability
        and (_number(card.get("edge")) or -1.0) >= top_daily_min_edge
        and _depth(card) >= top_daily_min_data_depth
    ]
    daily.sort(
        key=lambda card: (
            _number(card.get("expected_value")) or -999.0,
            _number(card.get("probability")) or 0.0,
            _depth(card),
        ),
        reverse=True,
    )
    daily = daily[: max(0, int(top_daily_limit))]

    value = []
    for card in cards:
        odds = _number(card.get("odds"))
        edge = _number(card.get("edge"))
        market = card.get("match_winner_market") if isinstance(card.get("match_winner_market"), dict) else {}
        gap = abs(
            (_number(market.get("player1_implied_probability")) or 0.0)
            - (_number(market.get("player2_implied_probability")) or 0.0)
        )
        if odds is None or odds <= value_min_odds or edge is None or edge <= 0:
            continue
        if gap > value_max_implied_gap:
            continue
        card = deepcopy(card)
        card["implied_probability_gap"] = gap
        value.append(card)
    value.sort(
        key=lambda card: (
            _number(card.get("edge")) or -999.0,
            _number(card.get("expected_value")) or -999.0,
            _number(card.get("probability")) or 0.0,
        ),
        reverse=True,
    )

    return {
        "top_daily_picks": daily,
        "value_picks": value,
        "ace_picks": [],
        "sg_picks": [],
        "market_selection": {
            "schema": 1,
            "current_outputs": ["match_winner"],
            "pending_outputs": ["aces", "double_faults", "sets", "games"],
            "odds_backed": True,
            "top_daily_rule": {
                "limit": int(top_daily_limit),
                "min_probability": top_daily_min_probability,
                "min_edge": top_daily_min_edge,
                "min_data_depth": top_daily_min_data_depth,
                "sort": "expected_value_desc_then_probability_then_data_depth",
            },
            "value_rule": {
                "min_odds": value_min_odds,
                "max_implied_probability_gap": value_max_implied_gap,
                "sort": "edge_desc",
            },
        },
    }


def attach_market_sections_to_feed(
    feed: dict[str, Any],
    enriched_predictions: list[dict[str, Any]],
    odds_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach live market presentation without changing prediction commitments."""
    result = deepcopy(feed)
    by_event = {
        str(row.get("event_id") or ""): row
        for row in enriched_predictions
        if isinstance(row, dict)
    }
    upcoming = []
    for base in result.get("upcoming", []):
        row = deepcopy(base)
        enriched = by_event.get(str(row.get("event_id") or ""))
        if enriched:
            for key in ("match_winner_market", "betting"):
                if isinstance(enriched.get(key), dict):
                    row[key] = deepcopy(enriched[key])
        upcoming.append(row)
    result["upcoming"] = upcoming

    sections = select_market_sections(enriched_predictions)
    result.update(sections)
    if odds_report is not None:
        result["market_selection"] = {
            **result.get("market_selection", {}),
            "odds_report": deepcopy(odds_report),
        }
    return result
