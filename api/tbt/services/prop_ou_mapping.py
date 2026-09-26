"""Pure PropLine Over/Under price mapping for *future* BlinQ projections.

This is a candidate selector, not publication or historical price recovery.
No settled results are consulted. Caller is responsible for matching events,
capturing odds before start, and validating API payload shape against a live sample.
"""
from __future__ import annotations

import math
import re
from typing import Any


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _selection_side(value: Any) -> str | None:
    text = _normalize(value)
    if re.search(r"\\bover\\b", text):
        return "over"
    if re.search(r"\\bunder\\b", text):
        return "under"
    return None


def _line(outcome: dict, market: dict) -> float | None:
    for value in (outcome.get("point"), market.get("point")):
        parsed = _number(value)
        if parsed is not None and parsed >= 0:
            return parsed
    for value in (outcome.get("name"), market.get("name")):
        match = re.search(r"\\b(?:over|under)\\s+(\\d+(?:\\.\\d+)?)", str(value or ""), re.I)
        if match:
            return float(match.group(1))
    return None


def _prob_over(mean: float, sd: float, line: float) -> float:
    """Continuity-corrected Gaussian predictive probability for integer counts."""
    threshold = math.floor(line) + 0.5
    return 0.5 * math.erfc((threshold - mean) / (math.sqrt(2) * sd))


def _set_prob(card: dict, line: float) -> float | None:
    best_of = int(card.get("best_of") or 3)
    # Existing BO3 model measures probability that three sets are played.
    if best_of == 3 and abs(line - 2.5) < 0.001:
        prob = _number(card.get("evidence_adjusted_probability"))
        if prob is not None:
            return min(0.99, max(0.01, prob))
        selected = _number(card.get("projection_confidence"))
        side = str(card.get("selection_id") or "").split(":")[1:2]
        if selected is not None and side:
            return selected if side[0] == "over" else 1 - selected
    # Other lines need a score-distribution model, not mean sets as probability.
    return None


def _probabilities(card: dict, line: float) -> tuple[float, float] | None:
    market = str(card.get("market") or "").lower()
    if market == "sets":
        p_over = _set_prob(card, line)
    else:
        mean = _number(card.get("projection"))
        if mean is None or mean < 0:
            return None
        if market == "games":
            sd = _number(card.get("projection_uncertainty"))
            sd = max(3.5 if int(card.get("best_of") or 3) == 3 else 5.5, sd or 0)
        elif market in ("aces", "double_faults"):
            # Conservative interim variance: replace with validated player
            # count distribution when enough paired real outcomes exist.
            sd = math.sqrt(max(1.44 if market == "aces" else 0.9025,
                               mean * (0.90 if market == "aces" else 1.10)))
        else:
            return None
        p_over = _prob_over(mean, sd, line)
    if p_over is None:
        return None
    return p_over, 1 - p_over


def _proper_outcomes(bookmaker: dict, market: dict, target_player: str | None):
    """Only pair an outcome with the requested player (or match-total market)."""
    key = str(market.get("key") or "")
    for outcome in market.get("outcomes") or []:
        if not isinstance(outcome, dict):
            continue
        side = _selection_side(outcome.get("name"))
        if side is None:
            continue
        if target_player is not None:
            description = _normalize(outcome.get("description") or market.get("description"))
            if not description or description != _normalize(target_player):
                continue
        line = _line(outcome, market)
        price = _number(outcome.get("price"))
        if line is None or price is None or price <= 1.0:
            continue
        yield {"bookmaker": bookmaker.get("title") or bookmaker.get("key"),
               "market_key": key, "side": side, "line": line, "odds": price}


def prop_ou_candidates(card: dict, odds_payload: dict) -> list[dict]:
    """Return priced U/O options on the matching contract, ordered by modeled EV.

    No historical publications are modified. No odds are synthesized.
    For player props, the selected person's projected count (not superiority
    confidence) drives the U/O probability.
    """
    metric = str(card.get("market") or "").lower()
    market_keys = {
        "aces": {"player_aces"},
        "double_faults": {"player_double_faults"},
        "games": {"totals", "total_games"},
        "sets": {"total_sets"},
    }.get(metric, set())
    player = card.get("projection_subject") or card.get("selection") if metric in ("aces", "double_faults") else None
    rows = []
    for book in odds_payload.get("bookmakers") or []:
        if not isinstance(book, dict):
            continue
        for market in book.get("markets") or []:
            if not isinstance(market, dict) or market.get("key") not in market_keys:
                continue
            for quote in _proper_outcomes(book, market, player):
                probs = _probabilities(card, quote["line"])
                if probs is None:
                    continue
                probability = probs[0] if quote["side"] == "over" else probs[1]
                rows.append({
                    **quote, "projection": card.get("projection"),
                    "model_probability": round(probability, 4),
                    "expected_value": round(probability * quote["odds"] - 1, 4),
                    "estimated_probability": True,
                    "price_source": "propline",
                })
    return sorted(rows, key=lambda x: (x["expected_value"], x["model_probability"]), reverse=True)


def best_ou_option(card: dict, odds_payload: dict, *, min_probability: float = 0.60) -> dict | None:
    """Find a candidate satisfying both probability and nonnegative modeled EV."""
    return next((x for x in prop_ou_candidates(card, odds_payload)
                 if x["model_probability"] >= min_probability and x["expected_value"] >= 0), None)
