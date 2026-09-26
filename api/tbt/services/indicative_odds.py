"""Compatibility boundary for legacy, uncalibrated confidence-derived odds.

The earlier formula converted model confidence into a bookmaker-looking number.
It was not trained on real O/U market prices and must never appear as a price.
Verified quotes are attached separately by projection_odds.py. Future market
price estimates require an independently validated calibration model.
"""
from __future__ import annotations

PROJECTION_MARKETS = {"aces", "double_faults", "games", "sets"}
ESTIMATE_MODEL = "uncalibrated_confidence_pricing_disabled"
LEGACY_ESTIMATE_FIELDS = (
    "indicative_odds", "indicative_odds_method",
    "indicative_odds_probability", "indicative_odds_scope",
)


def indicative_price(record: dict) -> None:
    """Fail closed until actual market prices support validated calibration."""
    return None


def annotate_feed_indicative_odds(feed: dict) -> tuple[dict, dict]:
    """Strip stale legacy estimates from the serving feed, leave real odds alone.

    Historical ledger / immutable result snapshots remain unchanged; this
    function decorates only the serving feed at publication time.
    """
    removed = {market: 0 for market in PROJECTION_MARKETS}
    for section in ("ace_picks", "sg_picks"):
        for card in feed.get(section, []) or []:
            if not isinstance(card, dict):
                continue
            market = str(card.get("market") or "").lower()
            if market in removed and any(key in card for key in LEGACY_ESTIMATE_FIELDS):
                removed[market] += 1
            for key in LEGACY_ESTIMATE_FIELDS:
                card.pop(key, None)
    for row in feed.get("results", []) or []:
        if not isinstance(row, dict):
            continue
        for pub in row.get("market_publications", []) or []:
            if not isinstance(pub, dict):
                continue
            market = str(pub.get("market") or "").lower()
            if market in removed and any(key in pub for key in LEGACY_ESTIMATE_FIELDS):
                removed[market] += 1
            for key in LEGACY_ESTIMATE_FIELDS:
                pub.pop(key, None)
    return feed, {
        "schema": 2,
        "method": ESTIMATE_MODEL,
        "historic_estimates_total": 0,
        "historic_estimates_by_market": dict.fromkeys(PROJECTION_MARKETS, 0),
        "legacy_estimates_removed_from_feed": removed,
        "real_bookmaker_roi_unmodified": True,
        "next_step": "collect_exact_premarket_odds_and_validate_calibration",
    }
