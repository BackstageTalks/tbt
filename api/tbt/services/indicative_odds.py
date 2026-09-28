"""Display-only indicative prices for unpriced projection cards.

Never represent these values as archived or live bookmaker quotes and never feed
them into real-money betting ROI. ACES/Double Faults use a stable illustrative
1.50–1.70 display range; Games/Sets retain the confidence-derived estimate.
Actual result, realized win rate and match outcome are never consulted.
"""
from __future__ import annotations

import math
import hashlib
from typing import Any

PROJECTION_MARKETS = {"aces", "double_faults", "games", "sets"}
ACE_DF_MARKETS = {"aces", "double_faults"}
ESTIMATE_MODEL = "frozen_projection_confidence_v1"
ACE_DF_DISPLAY_MODEL = "stable_illustrative_150_170_v1"
DISPLAY_OVERROUND = 0.055
ACE_DF_DISPLAY_MIN = 1.50
ACE_DF_DISPLAY_MAX = 1.70


def _number(value: Any) -> float | None:
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return None
    return candidate if math.isfinite(candidate) else None


def _stable_ace_df_display_price(record: dict) -> float | None:
    """Return one repeatable 1.50–1.70 display value for the same projection."""
    market = str(record.get("market") or record.get("projection_metric") or "").lower()
    identity = "|".join((
        str(record.get("event_id") or record.get("match_id") or record.get("id") or ""),
        market,
        str(record.get("selection_id") or record.get("selection") or record.get("pick") or ""),
        str(record.get("scheduled_at") or record.get("date") or ""),
    ))
    if not identity.replace("|", ""):
        return None
    cents = int.from_bytes(
        hashlib.sha256(identity.encode("utf-8")).digest()[:4], "big"
    ) % 21
    return round(ACE_DF_DISPLAY_MIN + cents / 100, 2)


def indicative_price(record: dict) -> dict | None:
    """Return a display-only decimal price without creating a fake bookmaker quote.

    ACES and Double Faults use the agreed stable illustrative 1.50–1.70 range.
    The number is deterministic per projection so it cannot jump on each render.
    It stays in indicative_odds only; odds and price_status remain untouched,
    therefore settlement, EV and real betting ROI cannot consume it.
    Games/Sets keep the older confidence-derived display estimate.
    """
    if not isinstance(record, dict):
        return None
    market = str(record.get("market") or record.get("projection_metric") or "").lower()
    if market not in PROJECTION_MARKETS:
        return None
    real_odds = _number(record.get("odds"))
    if real_odds is not None and real_odds > 1:
        return None
    confidence = _number(record.get("projection_confidence"))
    if confidence is None or confidence < 0.5 or confidence > 1.0:
        return None

    if market in ACE_DF_MARKETS:
        price = _stable_ace_df_display_price(record)
        if price is None:
            return None
        return {
            "indicative_odds": price,
            "indicative_odds_method": ACE_DF_DISPLAY_MODEL,
            "indicative_odds_probability": None,
            "indicative_odds_scope": (
                "display_only_illustrative_150_170_not_bookmaker_not_real_roi"
            ),
        }

    # Wide bounds avoid excessive apparent certainty from point projections.
    p = min(0.94, max(0.50, confidence))
    price = max(1.05, min(2.50, 1.0 / (p * (1.0 + DISPLAY_OVERROUND))))
    return {
        "indicative_odds": round(price + 1e-9, 2),
        "indicative_odds_method": ESTIMATE_MODEL,
        "indicative_odds_probability": round(p, 4),
        "indicative_odds_scope": "display_only_not_bookmaker_not_real_roi",
    }


def historical_display_placeholder(publication: dict, *, event_id: str = "") -> dict | None:
    """Stable, obviously illustrative 1.50–1.70 table filler, NEVER a quote.

    Historical public result view only. Stored under a dedicated display field,
    not publication.odds, never under price_status=priced_projection, never
    considered by ROI or settlement. Hashing avoids reshuffling on every refresh
    and is strictly independent of win/loss, profit, and model confidence.
    """
    if not isinstance(publication, dict):
        return None
    market = str(publication.get("market") or "").strip().lower()
    if market not in PROJECTION_MARKETS or not publication.get("issued_at"):
        return None
    actual = _number(publication.get("odds"))
    if actual is not None and actual > 1:
        return None
    identity = "|".join((
        str(event_id),
        market,
        str(publication.get("publication_key") or publication.get("selection_key") or ""),
        str(publication.get("selection_id") or publication.get("selection") or ""),
        str(publication["issued_at"]),
    ))
    if not identity.replace("|", ""):
        return None
    step = int.from_bytes(hashlib.sha256(identity.encode("utf-8")).digest()[:4], "big") % 21
    return {
        "historical_display_placeholder_odds": round(1.50 + step / 100, 2),
        "historical_display_placeholder_source": "synthetic_illustrative_not_bookmaker",
        "historical_display_placeholder_scope": "results_table_only_excluded_from_roi",
    }


def annotate_feed_indicative_odds(feed: dict) -> tuple[dict, dict]:
    """Decorate current picks and historical public results, never the ledger."""
    counts = {"aces": 0, "double_faults": 0, "games": 0, "sets": 0}
    for section in ("ace_picks", "sg_picks"):
        for card in feed.get(section, []) or []:
            estimate = indicative_price(card)
            if estimate is not None:
                card.update(estimate)
    historical_placeholder_counts = {market: 0 for market in PROJECTION_MARKETS}
    for row in feed.get("results", []) or []:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id") or row.get("match_id") or row.get("id") or "")
        for publication in row.get("market_publications", []) or []:
            if not isinstance(publication, dict):
                continue
            placeholder = historical_display_placeholder(publication, event_id=event_id)
            if placeholder is not None:
                publication.update(placeholder)
                # Do not attach the uncalibrated confidence-derived estimate to
                # an illustrative historical placeholder.
                for key in ("indicative_odds", "indicative_odds_method",
                            "indicative_odds_probability", "indicative_odds_scope"):
                    publication.pop(key, None)
                market = str(publication.get("market") or "").lower()
                historical_placeholder_counts[market] += 1
                continue
            estimate = indicative_price(publication)
            if estimate is None:
                continue
            publication.update(estimate)
            market = str(publication.get("market") or "").lower()
            counts[market] += 1
    return feed, {
        "schema": 2, "method": ESTIMATE_MODEL,
        "display_overround": DISPLAY_OVERROUND,
        "historic_estimates_by_market": counts,
        "historic_estimates_total": sum(counts.values()),
        "historical_illustrative_only_by_market": historical_placeholder_counts,
        "historical_illustrative_only_total": sum(historical_placeholder_counts.values()),
        "historical_illustrative_policy": (
            "synthetic_visible_label_not_historical_quote_never_used_for_roi"
        ),
        "real_bookmaker_roi_unmodified": True,
    }
