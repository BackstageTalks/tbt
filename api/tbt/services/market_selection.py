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

# Match Winner selection policy v1. These are intentionally explicit and
# auditable; they are working production defaults, not claims of guaranteed
# profitability. Future changes should be promoted only after OOS/live review.
MAIN_MIN_PROBABILITY = 0.78
MAIN_MIN_DATA_DEPTH = 0.80
MAIN_MIN_SURFACE_MATCHES = 5
DAILY_MIN_ODDS = 1.25
DAILY_MAX_ODDS = 1.50
VALUE_MIN_PROBABILITY = 0.60
VALUE_MIN_DATA_DEPTH = 0.80
VALUE_MIN_SURFACE_MATCHES = 5
VALUE_MAX_IMPLIED_GAP = 0.15


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


def _surface_samples(row: dict[str, Any]) -> tuple[int, int]:
    """Return observed surface-history counts for both players.

    Missing/invalid quality metadata is intentionally treated as zero. The
    selector must fail closed rather than promoting a row whose surface depth
    cannot be demonstrated from the published point-in-time quality block.
    """
    quality = row.get("quality") if isinstance(row.get("quality"), dict) else {}
    p1 = quality.get("player1") if isinstance(quality.get("player1"), dict) else {}
    p2 = quality.get("player2") if isinstance(quality.get("player2"), dict) else {}

    def count(value: Any) -> int:
        number = _number(value)
        if number is None or number < 0:
            return 0
        return int(number)

    return count(p1.get("surface_matches")), count(p2.get("surface_matches"))


def _passes_candidate_gate(
    row: dict[str, Any],
    *,
    min_probability: float,
    min_data_depth: float,
    min_surface_matches: int,
) -> bool:
    p1_surface, p2_surface = _surface_samples(row)
    return (
        _confidence(row) >= float(min_probability)
        and _depth(row) >= float(min_data_depth)
        and p1_surface >= int(min_surface_matches)
        and p2_surface >= int(min_surface_matches)
    )


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
    candidate_min_probability: float = VALUE_MIN_PROBABILITY,
    candidate_min_data_depth: float = VALUE_MIN_DATA_DEPTH,
    candidate_min_surface_matches: int = VALUE_MIN_SURFACE_MATCHES,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch provider-1 odds only for plausible published betting candidates.

    Odds calls are intentionally *not* spent on the entire upcoming board.
    The broad 60/80/5 gate is wide enough to cover both the main Daily/Prime
    pool and the separate close-market Value discovery branch, while keeping
    provider usage bounded.
    """
    start, end, day_key = betting_day_bounds(
        now, timezone_name=timezone_name, start_hour=start_hour
    )
    indexed = {str(row.get("event_id") or ""): deepcopy(row) for row in predictions}
    candidates = []
    for row in indexed.values():
        scheduled = _prediction_time(row)
        if scheduled is None or not start <= scheduled < end:
            continue
        if not _passes_candidate_gate(
            row,
            min_probability=candidate_min_probability,
            min_data_depth=candidate_min_data_depth,
            min_surface_matches=candidate_min_surface_matches,
        ):
            continue
        candidates.append(row)
    # Spend scarce odds calls on the strongest/data-richest predictions first.
    candidates.sort(key=lambda row: (_confidence(row), _depth(row)), reverse=True)
    eligible_candidates = len(candidates)
    if max_events > 0:
        candidates = candidates[:max_events]

    report = {
        "betting_day": day_key,
        "timezone": timezone_name,
        "start_hour": int(start_hour),
        "candidates": len(candidates),
        "eligible_candidates": eligible_candidates,
        "limited_out": max(0, eligible_candidates - len(candidates)),
        "max_events": int(max_events),
        "odds_requested": 0,
        "odds_available": 0,
        "odds_unavailable": 0,
        "errors": 0,
        "provider_id": int(provider_id),
        "candidate_gate": {
            "min_probability": float(candidate_min_probability),
            "min_data_depth": float(candidate_min_data_depth),
            "min_surface_matches_each": int(candidate_min_surface_matches),
        },
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
    # Publication candidates are private ledger state and must never be exposed
    # in the serving feed.
    card.pop("market_publication_candidates", None)
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
    ace_picks: list[dict[str, Any]] | None = None,
    sg_picks: list[dict[str, Any]] | None = None,
    main_min_probability: float = MAIN_MIN_PROBABILITY,
    main_min_data_depth: float = MAIN_MIN_DATA_DEPTH,
    main_min_surface_matches: int = MAIN_MIN_SURFACE_MATCHES,
    daily_min_odds: float = DAILY_MIN_ODDS,
    daily_max_odds: float = DAILY_MAX_ODDS,
    value_min_probability: float = VALUE_MIN_PROBABILITY,
    value_min_data_depth: float = VALUE_MIN_DATA_DEPTH,
    value_min_surface_matches: int = VALUE_MIN_SURFACE_MATCHES,
    value_max_implied_gap: float = VALUE_MAX_IMPLIED_GAP,
) -> dict[str, Any]:
    main_candidates = [
        row for row in predictions
        if _passes_candidate_gate(
            row,
            min_probability=main_min_probability,
            min_data_depth=main_min_data_depth,
            min_surface_matches=main_min_surface_matches,
        )
    ]
    value_candidates = [
        row for row in predictions
        if _passes_candidate_gate(
            row,
            min_probability=value_min_probability,
            min_data_depth=value_min_data_depth,
            min_surface_matches=value_min_surface_matches,
        )
    ]
    cards = [card for row in predictions if (card := _market_card(row)) is not None]

    # One common quality pool first; odds only decide which presentation bucket
    # a qualified Match Winner pick belongs to. Edge/EV remain diagnostics and
    # are deliberately not hard gates for Daily or Prime.
    main_pool = [
        card for card in cards
        if _passes_candidate_gate(
            card,
            min_probability=main_min_probability,
            min_data_depth=main_min_data_depth,
            min_surface_matches=main_min_surface_matches,
        )
    ]

    daily = []
    prime = []
    for card in main_pool:
        odds = _number(card.get("odds"))
        if odds is None:
            continue
        if float(daily_min_odds) <= odds <= float(daily_max_odds):
            daily.append(card)
        elif odds > float(daily_max_odds):
            prime.append(card)

    daily.sort(
        key=lambda card: (
            _number(card.get("probability")) or 0.0,
            _depth(card),
            -(_number(card.get("odds")) or 999.0),
        ),
        reverse=True,
    )
    prime.sort(
        key=lambda card: (
            _number(card.get("probability")) or 0.0,
            _depth(card),
            _number(card.get("odds")) or 0.0,
        ),
        reverse=True,
    )

    value = []
    for card in cards:
        if not _passes_candidate_gate(
            card,
            min_probability=value_min_probability,
            min_data_depth=value_min_data_depth,
            min_surface_matches=value_min_surface_matches,
        ):
            continue
        market = card.get("match_winner_market") if isinstance(card.get("match_winner_market"), dict) else {}
        p1_market = _number(market.get("player1_implied_probability"))
        p2_market = _number(market.get("player2_implied_probability"))
        if p1_market is None or p2_market is None:
            continue
        gap = abs(p1_market - p2_market)
        if gap > value_max_implied_gap:
            continue
        card = deepcopy(card)
        card["implied_probability_gap"] = gap
        card["close_market"] = True
        value.append(card)
    value.sort(
        key=lambda card: (
            _number(card.get("probability")) or 0.0,
            _depth(card),
            -(_number(card.get("implied_probability_gap")) or 1.0),
        ),
        reverse=True,
    )

    return {
        "top_daily_picks": daily,
        "prime_picks": prime,
        "value_picks": value,
        "ace_picks": deepcopy(ace_picks or []),
        "sg_picks": deepcopy(sg_picks or []),
        "market_selection": {
            "schema": 4,
            "selection_counts": {
                "main_candidates_before_odds": len(main_candidates),
                "value_candidates_before_odds": len(value_candidates),
                "priced_match_winner_rows": len(cards),
                "priced_main_quality_pool": len(main_pool),
                "daily": len(daily),
                "prime": len(prime),
                "value": len(value),
            },
            "current_outputs": (
                ["match_winner"]
                + (["aces_projection", "double_faults_projection"] if ace_picks else [])
                + (["sets_projection", "games_projection"] if sg_picks else [])
            ),
            "pending_outputs": ["aces_odds", "double_faults_odds", "sets_odds", "games_odds"],
            # Legacy flag remains true because Match Winner / Daily / Prime / Value are
            # odds-backed. The explicit lists below prevent projection-only
            # Ace/S-G outputs from being mistaken for priced selections.
            "odds_backed": True,
            "odds_backed_outputs": ["match_winner"],
            "projection_only_outputs": (
                (["aces_projection", "double_faults_projection"] if ace_picks else [])
                + (["sets_projection", "games_projection"] if sg_picks else [])
            ),
            "main_candidate_rule": {
                "min_probability": float(main_min_probability),
                "min_data_depth": float(main_min_data_depth),
                "min_surface_matches_each": int(main_min_surface_matches),
                "edge_filter": False,
            },
            "daily_rule": {
                "min_odds": float(daily_min_odds),
                "max_odds": float(daily_max_odds),
                "sort": "probability_desc_then_data_depth",
            },
            # Backward-compatible metadata key for older clients. The section
            # is now product-labelled Daily Picks and has no artificial top-10
            # truncation.
            "top_daily_rule": {
                "limit": None,
                "min_probability": float(main_min_probability),
                "min_data_depth": float(main_min_data_depth),
                "min_surface_matches_each": int(main_min_surface_matches),
                "min_odds": float(daily_min_odds),
                "max_odds": float(daily_max_odds),
                "edge_filter": False,
                "sort": "probability_desc_then_data_depth",
            },
            "prime_rule": {
                "min_odds_exclusive": float(daily_max_odds),
                "max_odds": None,
                "sort": "probability_desc_then_data_depth",
            },
            "value_rule": {
                "selection_mode": "close_market_model_winner",
                "min_probability": float(value_min_probability),
                "min_data_depth": float(value_min_data_depth),
                "min_surface_matches_each": int(value_min_surface_matches),
                "max_implied_probability_gap": float(value_max_implied_gap),
                "edge_filter": False,
                "edge_display_only": True,
                "sort": "probability_desc_then_data_depth_then_market_closeness",
            },
        },
    }



def annotate_market_publication_candidates(
    predictions: list[dict[str, Any]],
    *,
    main_min_probability: float = MAIN_MIN_PROBABILITY,
    main_min_data_depth: float = MAIN_MIN_DATA_DEPTH,
    main_min_surface_matches: int = MAIN_MIN_SURFACE_MATCHES,
    daily_min_odds: float = DAILY_MIN_ODDS,
    daily_max_odds: float = DAILY_MAX_ODDS,
    value_min_probability: float = VALUE_MIN_PROBABILITY,
    value_min_data_depth: float = VALUE_MIN_DATA_DEPTH,
    value_min_surface_matches: int = VALUE_MIN_SURFACE_MATCHES,
    value_max_implied_gap: float = VALUE_MAX_IMPLIED_GAP,
) -> list[dict[str, Any]]:
    """Attach pending section-publication candidates to current market rows.

    The core Match Winner prediction has its own publication lifecycle. Betting
    sections (Daily / Prime / Value) may become available later when provider
    odds arrive, so they need independent publication records. These candidates
    are only *pending* here; `confirm_prediction_publication.py` stamps issued_at
    after the exact feed has been deployed successfully.

    One event can legitimately be published in more than one section. Each
    section gets its own price snapshot, while `selection_key` lets performance
    reporting deduplicate the same underlying bet for overall ROI.
    """
    sections = select_market_sections(
        predictions,
        main_min_probability=main_min_probability,
        main_min_data_depth=main_min_data_depth,
        main_min_surface_matches=main_min_surface_matches,
        daily_min_odds=daily_min_odds,
        daily_max_odds=daily_max_odds,
        value_min_probability=value_min_probability,
        value_min_data_depth=value_min_data_depth,
        value_min_surface_matches=value_min_surface_matches,
        value_max_implied_gap=value_max_implied_gap,
    )
    membership: dict[str, list[str]] = {}
    for section_name, key in (
        ("top_daily", "top_daily_picks"),
        ("prime", "prime_picks"),
        ("value", "value_picks"),
    ):
        for row in sections.get(key, []):
            event_id = str(row.get("event_id") or "").strip()
            if event_id:
                membership.setdefault(event_id, []).append(section_name)

    annotated: list[dict[str, Any]] = []
    for source in predictions:
        row = deepcopy(source)
        event_id = str(row.get("event_id") or "").strip()
        betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
        sections_for_event = membership.get(event_id, [])
        publications: list[dict[str, Any]] = []
        if betting.get("market") == "match_winner" and sections_for_event:
            selection_id = str(betting.get("selection_id") or "").strip()
            betting_day = str(betting.get("betting_day") or "").strip()
            if selection_id:
                selection_key = f"match_winner:{betting_day}:{event_id}:{selection_id}"
                for section_name in sections_for_event:
                    publications.append({
                        "schema": 1,
                        "publication_key": f"{section_name}:{selection_key}",
                        "selection_key": selection_key,
                        "section": section_name,
                        "market": "match_winner",
                        "selection": betting.get("selection"),
                        "selection_id": selection_id,
                        "odds": betting.get("odds"),
                        "fair_implied_probability": betting.get("fair_implied_probability"),
                        "model_probability": betting.get("model_probability"),
                        "edge": betting.get("edge"),
                        "expected_value": betting.get("expected_value"),
                        "provider_id": betting.get("provider_id"),
                        "captured_at": betting.get("captured_at"),
                        "betting_day": betting_day or None,
                        "issued_at": None,
                        "publication_status": "pending",
                        "result": None,
                    })
        row["market_publication_candidates"] = publications
        annotated.append(row)
    return annotated

def attach_market_sections_to_feed(
    feed: dict[str, Any],
    enriched_predictions: list[dict[str, Any]],
    odds_report: dict[str, Any] | None = None,
    *,
    ace_picks: list[dict[str, Any]] | None = None,
    ace_report: dict[str, Any] | None = None,
    sg_picks: list[dict[str, Any]] | None = None,
    sg_report: dict[str, Any] | None = None,
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

    sections = select_market_sections(
        enriched_predictions, ace_picks=ace_picks, sg_picks=sg_picks
    )
    result.update(sections)
    result["market_selection"] = {
        **result.get("market_selection", {}),
        "publication_schema": 1,
    }
    if odds_report is not None:
        result["market_selection"] = {
            **result.get("market_selection", {}),
            "odds_report": deepcopy(odds_report),
        }
    if ace_report is not None:
        result["market_selection"] = {
            **result.get("market_selection", {}),
            "ace_projection_report": deepcopy(ace_report),
        }
    if sg_report is not None:
        result["market_selection"] = {
            **result.get("market_selection", {}),
            "sg_projection_report": deepcopy(sg_report),
        }
    return result
