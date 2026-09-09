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

# Match Winner selection policy v2. These are working production defaults,
# deliberately configurable and auditable. They are not claims of guaranteed
# profitability; threshold promotion belongs behind OOS/live review.
#
# Public sections are mutually exclusive. A selection may qualify internally for
# more than one strategy, but it is assigned to exactly one primary section in
# the order below so the same bet never appears twice on the BlinQ dashboard.
SECTION_PRIORITY = ("prime", "top_daily", "value")

# PRIME = accuracy first. Odds are not a hard band; 1.20-1.50 is merely the
# preferred product zone. Only materially negative EV is rejected.
PRIME_MIN_PROBABILITY = 0.85
PRIME_MIN_DATA_DEPTH = 0.80
PRIME_MIN_SURFACE_MATCHES = 5
PRIME_MAX_NEGATIVE_EV = -0.03
PRIME_PREFERRED_MIN_ODDS = 1.20
PRIME_PREFERRED_MAX_ODDS = 1.50
PRIME_LIMIT = 30

# TOP BETS = strongest remaining model picks after Prime. `top_daily` remains
# the internal compatibility key used by the existing feed/publication ledger.
# The selector uses an adaptive confidence cascade validated against the large
# walk-forward backtest: start at 75%, then 72%, 70%, and only finally 68%.
# As soon as a tier brings the remaining Top Bets set to at least ten, selection
# stops and ALL qualifying picks in that tier are kept. The dashboard previews
# only ten; the feed itself is not truncated by a presentation limit.
TOP_PREFERRED_PROBABILITY = 0.75
TOP_SECONDARY_PROBABILITY = 0.72
TOP_STANDARD_PROBABILITY = 0.70
TOP_MIN_PROBABILITY = 0.68
TOP_TARGET_COUNT = 10
TOP_MIN_DATA_DEPTH = 0.80
TOP_MIN_SURFACE_MATCHES = 5
TOP_MIN_ODDS: float | None = 1.20
TOP_MIN_EDGE: float | None = None
TOP_MIN_EXPECTED_VALUE: float | None = None
TOP_LIMIT: int | None = None

# VALUE = edge/EV first. This branch intentionally accepts lower model win
# probability than Prime/Top, but demands a stronger price disagreement.
VALUE_MIN_PROBABILITY = 0.55
VALUE_MIN_DATA_DEPTH = 0.75
VALUE_MIN_SURFACE_MATCHES = 3
VALUE_MIN_ODDS = 1.80
VALUE_MIN_EDGE = 0.05
VALUE_MIN_EXPECTED_VALUE = 0.08
VALUE_LIMIT: int | None = None


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


def _overall_samples(row: dict[str, Any]) -> tuple[int, int]:
    """Return point-in-time overall match counts for both players."""
    quality = row.get("quality") if isinstance(row.get("quality"), dict) else {}
    p1 = quality.get("player1") if isinstance(quality.get("player1"), dict) else {}
    p2 = quality.get("player2") if isinstance(quality.get("player2"), dict) else {}

    def count(value: Any) -> int:
        number = _number(value)
        if number is None or number < 0:
            return 0
        return int(number)

    return count(p1.get("matches")), count(p2.get("matches"))


def _top_rank_key(card: dict[str, Any]) -> tuple[float, float, int, int, float]:
    """Confidence-first Top Bets ranking.

    Elo, surface Elo, H2H and form already contribute to model probability.
    The remaining terms measure how well-supported that probability is; price is
    deliberately only the final tiebreaker and edge/EV are not ranking inputs.
    """
    p1_surface, p2_surface = _surface_samples(card)
    p1_matches, p2_matches = _overall_samples(card)
    return (
        _number(card.get("probability")) or 0.0,
        _depth(card),
        min(p1_surface, p2_surface),
        min(p1_matches, p2_matches),
        _number(card.get("odds")) or 0.0,
    )




def _top_cascade_select(
    cards: list[dict[str, Any]],
    *,
    minimum_probability: float = TOP_MIN_PROBABILITY,
    target_count: int = TOP_TARGET_COUNT,
) -> tuple[list[dict[str, Any]], float | None, dict[str, int]]:
    """Select all cards in the first confidence tier that reaches the target.

    The input must already exclude Prime selections. This makes the cascade match
    the public product semantics: Top Bets are the strongest *remaining* picks.
    Lower tiers are fallback inventory, not mandatory filler.
    """
    minimum = float(minimum_probability)
    thresholds = [
        TOP_PREFERRED_PROBABILITY,
        TOP_SECONDARY_PROBABILITY,
        TOP_STANDARD_PROBABILITY,
        minimum,
    ]
    thresholds = sorted({max(minimum, float(value)) for value in thresholds}, reverse=True)
    counts: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    applied_floor: float | None = None
    for threshold in thresholds:
        selected = [card for card in cards if (_number(card.get("probability")) or 0.0) >= threshold]
        counts[f"{threshold:.2f}"] = len(selected)
        applied_floor = threshold
        if len(selected) >= int(target_count):
            break
    return selected, applied_floor, counts

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
    The broad Value floor is used for pre-price discovery so odds calls can cover
    every currently supported Match Winner branch. Final Prime/Top/Value rules
    remain stricter and are applied after prices are attached.
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


def _selection_identity(row: dict[str, Any]) -> str:
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    event_id = str(row.get("event_id") or row.get("id") or "").strip()
    selection_id = str(betting.get("selection_id") or row.get("selection_id") or "").strip()
    market = str(betting.get("market") or row.get("market") or "match_winner").strip()
    betting_day = str(betting.get("betting_day") or row.get("betting_day") or "").strip()
    return f"{market}:{betting_day}:{event_id}:{selection_id}"


def _passes_price_guardrails(
    card: dict[str, Any],
    *,
    min_odds: float | None = None,
    min_edge: float | None = None,
    min_expected_value: float | None = None,
    min_expected_value_inclusive: float | None = None,
) -> bool:
    odds = _number(card.get("odds"))
    edge = _number(card.get("edge"))
    expected_value = _number(card.get("expected_value"))
    if min_odds is not None and (odds is None or odds < float(min_odds)):
        return False
    if min_edge is not None and (edge is None or edge < float(min_edge)):
        return False
    if min_expected_value is not None and (
        expected_value is None or expected_value < float(min_expected_value)
    ):
        return False
    if min_expected_value_inclusive is not None and (
        expected_value is None
        or expected_value < float(min_expected_value_inclusive)
    ):
        return False
    return True


def _exclusive_section_assignment(
    qualified: dict[str, list[dict[str, Any]]],
    *,
    priority: tuple[str, ...] = SECTION_PRIORITY,
    limits: dict[str, int | None] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int], dict[str, int]]:
    """Assign every *published* selection to at most one public section.

    Limits are applied during priority assignment, not afterwards. A row that is
    #11 for Top Bets is therefore not reserved/hidden from Value merely because
    it qualified for Top; only actually selected public offers consume identity.
    """
    selected = {name: [] for name in qualified}
    used: set[str] = set()
    removed = {name: 0 for name in qualified}
    limited_out = {name: 0 for name in qualified}
    limits = limits or {}

    def assign(section: str, cards: list[dict[str, Any]]) -> None:
        raw_limit = limits.get(section)
        limit = None if raw_limit is None or raw_limit < 0 else int(raw_limit)
        for card in cards:
            identity = _selection_identity(card)
            if not identity or identity in used:
                removed[section] = removed.get(section, 0) + 1
                continue
            if limit is not None and len(selected.setdefault(section, [])) >= limit:
                limited_out[section] = limited_out.get(section, 0) + 1
                # Do not reserve identity: a lower-priority strategy may still
                # publish this row if it independently qualifies there.
                continue
            used.add(identity)
            item = deepcopy(card)
            item["primary_section"] = section
            selected.setdefault(section, []).append(item)

    for section in priority:
        assign(section, qualified.get(section, []))

    # Keep forward compatibility if a future caller supplies a section that is
    # not yet present in SECTION_PRIORITY.
    for section, cards in qualified.items():
        if section in priority:
            continue
        assign(section, cards)
    return selected, removed, limited_out


def select_market_sections(
    predictions: list[dict[str, Any]],
    *,
    prime_min_probability: float = PRIME_MIN_PROBABILITY,
    prime_min_data_depth: float = PRIME_MIN_DATA_DEPTH,
    prime_min_surface_matches: int = PRIME_MIN_SURFACE_MATCHES,
    prime_max_negative_ev: float = PRIME_MAX_NEGATIVE_EV,
    prime_limit: int | None = PRIME_LIMIT,
    top_min_probability: float = TOP_MIN_PROBABILITY,
    top_min_data_depth: float = TOP_MIN_DATA_DEPTH,
    top_min_surface_matches: int = TOP_MIN_SURFACE_MATCHES,
    top_min_odds: float | None = TOP_MIN_ODDS,
    top_min_edge: float | None = TOP_MIN_EDGE,
    top_min_expected_value: float | None = TOP_MIN_EXPECTED_VALUE,
    top_limit: int | None = TOP_LIMIT,
    value_min_probability: float = VALUE_MIN_PROBABILITY,
    value_min_data_depth: float = VALUE_MIN_DATA_DEPTH,
    value_min_surface_matches: int = VALUE_MIN_SURFACE_MATCHES,
    value_min_odds: float = VALUE_MIN_ODDS,
    value_min_edge: float = VALUE_MIN_EDGE,
    value_min_expected_value: float = VALUE_MIN_EXPECTED_VALUE,
    value_limit: int | None = VALUE_LIMIT,
    section_priority: tuple[str, ...] = SECTION_PRIORITY,
    ace_picks: list[dict[str, Any]] | None = None,
    sg_picks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cards = [card for row in predictions if (card := _market_card(row)) is not None]

    prime_qualified = []
    top_qualified = []
    value_qualified = []

    for card in cards:
        if _passes_candidate_gate(
            card,
            min_probability=prime_min_probability,
            min_data_depth=prime_min_data_depth,
            min_surface_matches=prime_min_surface_matches,
        ) and _passes_price_guardrails(
            card,
            min_expected_value_inclusive=prime_max_negative_ev,
        ):
            prime_qualified.append(card)

        if _passes_candidate_gate(
            card,
            min_probability=top_min_probability,
            min_data_depth=top_min_data_depth,
            min_surface_matches=top_min_surface_matches,
        ) and _passes_price_guardrails(
            card,
            min_odds=top_min_odds,
            min_edge=top_min_edge,
            min_expected_value=top_min_expected_value,
        ):
            top_qualified.append(card)

        if _passes_candidate_gate(
            card,
            min_probability=value_min_probability,
            min_data_depth=value_min_data_depth,
            min_surface_matches=value_min_surface_matches,
        ) and _passes_price_guardrails(
            card,
            min_odds=value_min_odds,
            min_edge=value_min_edge,
            min_expected_value=value_min_expected_value,
        ):
            value_qualified.append(card)

    # Strategy-specific ranking happens before exclusivity. Priority then decides
    # the public home for a selection that qualifies for multiple strategies.
    prime_qualified.sort(
        key=lambda card: (
            _number(card.get("probability")) or 0.0,
            _depth(card),
            _number(card.get("expected_value")) or -999.0,
        ),
        reverse=True,
    )
    top_qualified.sort(key=_top_rank_key, reverse=True)
    value_qualified.sort(
        key=lambda card: (
            _number(card.get("expected_value")) or -999.0,
            _number(card.get("edge")) or -999.0,
            _number(card.get("probability")) or 0.0,
            _depth(card),
        ),
        reverse=True,
    )

    # Assign Prime first, then run the adaptive Top Bets cascade only on
    # selections that genuinely remain after Prime. Value receives everything
    # still unclaimed. This preserves the one-underlying-pick/one-public-offer
    # invariant while making the Top cascade product-correct.
    prime_exclusive, prime_removed, prime_limited = _exclusive_section_assignment(
        {"prime": prime_qualified},
        priority=("prime",),
        limits={"prime": prime_limit},
    )
    prime = prime_exclusive.get("prime", [])
    claimed = {_selection_identity(card) for card in prime}

    top_remaining = [card for card in top_qualified if _selection_identity(card) not in claimed]
    top_duplicate_removed = len(top_qualified) - len(top_remaining)
    top_cascade, top_applied_floor, top_tier_counts = _top_cascade_select(
        top_remaining,
        minimum_probability=top_min_probability,
        target_count=TOP_TARGET_COUNT,
    )
    top_cascade_excluded = len(top_remaining) - len(top_cascade)
    if top_limit is not None:
        top = top_cascade[: max(0, int(top_limit))]
        top_limited_out = max(0, len(top_cascade) - len(top))
    else:
        top = top_cascade
        top_limited_out = 0
    claimed.update(_selection_identity(card) for card in top)

    value_remaining = [card for card in value_qualified if _selection_identity(card) not in claimed]
    value_duplicate_removed = len(value_qualified) - len(value_remaining)
    if value_limit is not None:
        value = value_remaining[: max(0, int(value_limit))]
        value_limited_out = max(0, len(value_remaining) - len(value))
    else:
        value = value_remaining
        value_limited_out = 0

    duplicate_removed = {
        "prime": int(prime_removed.get("prime", 0)),
        "top_daily": top_duplicate_removed,
        "value": value_duplicate_removed,
    }
    limited_out = {
        "prime": int(prime_limited.get("prime", 0)),
        "top_daily": top_limited_out,
        "value": value_limited_out,
    }

    selected_identities = [
        _selection_identity(card)
        for card in (prime + top + value)
    ]
    if len(selected_identities) != len(set(selected_identities)):
        raise ValueError("Market section exclusivity invariant failed")

    return {
        # Keep `top_daily_picks` as the stable feed key. Product label is Top Bets.
        "top_daily_picks": top,
        "prime_picks": prime,
        "value_picks": value,
        "ace_picks": deepcopy(ace_picks or []),
        "sg_picks": deepcopy(sg_picks or []),
        "market_selection": {
            "schema": 7,
            "selection_policy": "prime_top_value_v4_adaptive_top_cascade",
            "selection_counts": {
                "priced_match_winner_rows": len(cards),
                "prime_qualified_before_exclusivity": len(prime_qualified),
                "top_qualified_before_exclusivity": len(top_qualified),
                "value_qualified_before_exclusivity": len(value_qualified),
                "prime": len(prime),
                "top_daily": len(top),
                "value": len(value),
                "duplicates_removed": sum(duplicate_removed.values()),
                "limited_out": sum(limited_out.values()),
                "top_cascade_excluded": int(top_cascade_excluded),
            },
            "exclusive_assignment": {
                "enabled": True,
                "priority": list(section_priority),
                "dedupe_key": "market:betting_day:event_id:selection_id",
                "duplicates_removed_by_section": duplicate_removed,
                "limited_out_by_section": limited_out,
                "limit_aware": True,
            },
            "top_cascade": {
                "target_count": int(TOP_TARGET_COUNT),
                "tiers": [
                    float(TOP_PREFERRED_PROBABILITY),
                    float(TOP_SECONDARY_PROBABILITY),
                    float(TOP_STANDARD_PROBABILITY),
                    float(top_min_probability),
                ],
                "applied_floor": None if top_applied_floor is None else float(top_applied_floor),
                "remaining_after_prime": len(top_remaining),
                "tier_counts": top_tier_counts,
                "selected_before_optional_hard_limit": len(top_cascade),
                "presentation_preview_limit": 10,
            },
            "current_outputs": (
                ["match_winner"]
                + (["aces_projection", "double_faults_projection"] if ace_picks else [])
                + (["sets_projection", "games_projection"] if sg_picks else [])
            ),
            "pending_outputs": ["aces_odds", "double_faults_odds", "sets_odds", "games_odds"],
            "odds_backed": True,
            "odds_backed_outputs": ["match_winner"],
            "projection_only_outputs": (
                (["aces_projection", "double_faults_projection"] if ace_picks else [])
                + (["sets_projection", "games_projection"] if sg_picks else [])
            ),
            # Compatibility metadata retained for older clients that still read
            # `main_candidate_rule` / `top_daily_rule`.
            "main_candidate_rule": {
                "min_probability": float(prime_min_probability),
                "min_data_depth": float(prime_min_data_depth),
                "min_surface_matches_each": int(prime_min_surface_matches),
                "edge_filter": False,
            },
            "prime_rule": {
                "objective": "accuracy_first",
                "min_probability": float(prime_min_probability),
                "min_data_depth": float(prime_min_data_depth),
                "min_surface_matches_each": int(prime_min_surface_matches),
                "preferred_min_odds": float(PRIME_PREFERRED_MIN_ODDS),
                "preferred_max_odds": float(PRIME_PREFERRED_MAX_ODDS),
                "max_negative_expected_value": float(prime_max_negative_ev),
                "hard_odds_band": False,
                "limit": prime_limit,
                "sort": "probability_desc_then_data_depth_then_ev",
            },
            "top_daily_rule": {
                "product_label": "Top Bets",
                "objective": "confidence_first",
                "preferred_probability": float(TOP_PREFERRED_PROBABILITY),
                "secondary_probability": float(TOP_SECONDARY_PROBABILITY),
                "standard_probability": float(TOP_STANDARD_PROBABILITY),
                "min_probability": float(top_min_probability),
                "target_count": int(TOP_TARGET_COUNT),
                "min_data_depth": float(top_min_data_depth),
                "min_surface_matches_each": int(top_min_surface_matches),
                "requires_odds": True,
                "min_odds": None if top_min_odds is None else float(top_min_odds),
                "min_edge": None if top_min_edge is None else float(top_min_edge),
                "min_expected_value": (
                    None if top_min_expected_value is None else float(top_min_expected_value)
                ),
                "edge_ev_role": "diagnostic_only",
                "limit": top_limit,
                "presentation_preview_limit": 10,
                "cascade": "75_then_72_then_70_then_68_until_at_least_10_keep_full_tier",
                "sort": "probability_desc_then_depth_then_surface_sample_then_overall_sample_then_odds",
            },
            "value_rule": {
                "objective": "edge_ev_first",
                "min_probability": float(value_min_probability),
                "min_data_depth": float(value_min_data_depth),
                "min_surface_matches_each": int(value_min_surface_matches),
                "min_odds": float(value_min_odds),
                "min_edge": float(value_min_edge),
                "min_expected_value": float(value_min_expected_value),
                "limit": value_limit,
                "sort": "ev_desc_then_edge_then_probability",
            },
        },
    }



def annotate_market_publication_candidates(
    predictions: list[dict[str, Any]],
    **selection_kwargs: Any,
) -> list[dict[str, Any]]:
    """Attach one pending betting-section publication per underlying pick.

    A Match Winner selection can qualify for several internal strategies, but
    `select_market_sections()` resolves it to a single primary public section.
    The ledger therefore mirrors the dashboard: one selection, one offer.
    """
    sections = select_market_sections(predictions, **selection_kwargs)
    membership: dict[str, str] = {}
    for section_name, key in (
        ("prime", "prime_picks"),
        ("top_daily", "top_daily_picks"),
        ("value", "value_picks"),
    ):
        for item in sections.get(key, []):
            identity = _selection_identity(item)
            if identity:
                if identity in membership:
                    raise ValueError("Selection assigned to multiple public market sections")
                membership[identity] = section_name

    annotated: list[dict[str, Any]] = []
    for source in predictions:
        row = deepcopy(source)
        betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
        publications: list[dict[str, Any]] = []
        identity = _selection_identity(row)
        section_name = membership.get(identity)
        if betting.get("market") == "match_winner" and section_name:
            event_id = str(row.get("event_id") or "").strip()
            selection_id = str(betting.get("selection_id") or "").strip()
            betting_day = str(betting.get("betting_day") or "").strip()
            if event_id and selection_id:
                selection_key = f"match_winner:{betting_day}:{event_id}:{selection_id}"
                publications.append({
                    "schema": 1,
                    "publication_key": f"{section_name}:{selection_key}",
                    "selection_key": selection_key,
                    "section": section_name,
                    "primary_section": section_name,
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
