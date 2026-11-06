"""Fail-closed presentation guard for extreme Match Winner price inversions.

Do not rewrite model predictions, provider/local quotes, frozen issuance or
results.  This guard is independent of source and does not optimize EV/ROI.
Its very conservative boundary only quarantines an inversion larger than
50 percentage points between the public probability and 1 / offered odds.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone


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


def _aware_utc_timestamp(value: object) -> datetime | None:
    """Reject unverified or timezone-naive quote/start timestamps."""
    try:
        parsed = (
            value if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def post_start_winner_quote(row: object) -> bool:
    """Quarantine an explicitly timestamped winner quote not proven pre-start.

    Missing capture evidence in legacy issued rows is deliberately not inferred
    to be post-start; this contract protects new priced rows without rewriting
    frozen history. The selected bet quote timestamp takes precedence; an
    unrelated provider-market refresh must not invalidate an earlier local bet.
    """
    if not isinstance(row, dict):
        return False
    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    if betting.get("market") not in (None, "", "match_winner"):
        return False
    market = (
        row.get("match_winner_market")
        if isinstance(row.get("match_winner_market"), dict) else {}
    )
    # The actionable price is betting.odds. Prefer the matching betting
    # capture timestamp, especially when a separately refreshed provider
    # market differs from an equally authoritative local quote.
    captured_value = betting.get("captured_at")
    if captured_value in (None, ""):
        captured_value = market.get("captured_at")
    if captured_value in (None, ""):
        return False
    start = _aware_utc_timestamp(row.get("scheduled_at"))
    captured = _aware_utc_timestamp(captured_value)
    return start is None or captured is None or captured >= start
