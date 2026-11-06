"""Fail-closed presentation guard for extreme Match Winner price inversions.

Do not rewrite model predictions, provider/local quotes, frozen issuance or
results.  This guard is independent of source and does not optimize EV/ROI.
Its very conservative boundary only quarantines an inversion larger than
50 percentage points between the public probability and 1 / offered odds.
"""
from __future__ import annotations

import math


def _finite_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def extreme_winner_price_inversion(probability: object, odds: object) -> bool:
    """Hold only radically inconsistent priced winner picks for review.

    This is an evidence-sanity quarantine, not an odds ceiling: a lower-model-
    probability longshot is not automatically rejected for its large price.
    Unpriced/malformed offers remain the responsibility of existing gates.
    """
    p = _finite_number(probability)
    price = _finite_number(odds)
    if p is None or price is None or not 0.5 <= p < 1.0 or price <= 1.0:
        return False
    return p - (1.0 / price) > 0.50 + 1e-12
