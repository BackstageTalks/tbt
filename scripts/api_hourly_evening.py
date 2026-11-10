"""Pure UTC provider-day ceiling for productive, bounded post-reset statistics.

The existing Azure CAS budget, provider header reserve, native writer lock,
and 5,000-request per-run cap remain authoritative. This policy only releases
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

SMOKE_SOURCE = "operator-approved-500-statistics-smoke"


def operator_smoke_request_cap(path, *, enabled: bool, now: datetime) -> int | None:
    """Apply a fresh operator's *restrictive* 500-call cap to one tick only.

    Only a non-dry-run, marker-approved push of the existing hourly tick can
    use this override. The existing shared CAS ledger, provider-header and
    writer checks remain authoritative.
    """
    if not enabled:
        return None

    import json
    from pathlib import Path

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("source") != SMOKE_SOURCE:
        return None
    if payload.get("schema") != 1 or type(payload.get("max_requests")) is not int or payload["max_requests"] != 500:
        raise ValueError("Invalid operator smoke request cap; no dispatch")

    requested = datetime.fromisoformat(str(payload.get("requested_utc", "")).replace("Z", "+00:00"))
    if requested.tzinfo is None or now.tzinfo is None:
        raise ValueError("Operator smoke request must use timezone-aware UTC")
    age = now.astimezone(timezone.utc) - requested.astimezone(timezone.utc)
    if not timedelta(0) <= age <= timedelta(minutes=25):
        raise ValueError("Operator smoke request expired or not yet valid; no dispatch")
    return 500
