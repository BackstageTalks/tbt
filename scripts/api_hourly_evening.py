"""Pure UTC provider-day ceiling for productive, bounded post-reset statistics.

The existing Azure CAS budget, provider header reserve, native writer lock,
and 3,000-request per-run cap remain authoritative. This policy only releases
part of the *already available* shared headroom after the 17:09 UTC reset,
leaving at least 6,000 calls below the 14,500 ceiling until daytime work.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def evening_cap(now: datetime, next_reset: datetime) -> int | None:
    """Return a staged shared-spend ceiling for 00:45..06:00 after UTC reset."""
    if now.tzinfo is None or next_reset.tzinfo is None:
        raise ValueError("Provider-day timestamps must be timezone-aware")
    elapsed = (now.astimezone(timezone.utc) -
               (next_reset.astimezone(timezone.utc) - timedelta(days=1))).total_seconds()
    if 45 * 60 <= elapsed < 6 * 3600:
        return min(8500, 3000 + 1200 * int(elapsed // 3600))
    return None
