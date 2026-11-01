"""Atomic global pacing of paid Tennis API calls across API workers.

A separate Azure Table row serializes six-per-second time slots. The shared
daily budget remains independent and authoritative. On storage error, no
provider request may start. This never touches the canonical CDB.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import time

from .budget import RequestBudgetExceeded

RATE_TABLE = "BlinQApiRate"
PARTITION = "rapidapi"
ROW = "pace-v1"
MAX_RPS = 6
MIN_GAP = 1.0 / MAX_RPS
MAX_RETRIES = 12


class SharedRateUnavailable(RequestBudgetExceeded):
    """Fail closed when global pacing cannot be verified."""


class SharedRateBusy(RequestBudgetExceeded):
    """A prior paid caller occupies the immediately preceding time slot."""
    def __init__(self, seconds):
        self.retry_after_seconds = max(0.005, float(seconds))
        super().__init__("Global Tennis API 6/s pace slot occupied")


def plan_pace(previous, *, now):
    """Pure global minimum-spacing reservation; no network/API/quota usage."""
    if not isinstance(now, (int, float)) or not 0 < float(now) < 1e14:
        raise ValueError("Invalid wall-clock timestamp")
    if previous is not None:
        if not isinstance(previous, dict) or previous.get("schema") != 1:
            raise SharedRateUnavailable("Invalid shared pacing schema")
        last = previous.get("last")
        if type(last) not in (int, float) or last < 0 or last > now + 2:
            raise SharedRateUnavailable("Invalid or future shared pace timestamp")
        remaining = float(last) + MIN_GAP - float(now)
        if remaining > 0:
            raise SharedRateBusy(remaining)
    return {"schema": 1, "last": float(now)}


def _conflict(exc):
    code = getattr(exc, "status_code", None)
    name = type(exc).__name__.lower()
    return code in (409, 412) or any(
        tag in name for tag in ("conflict", "precondition", "resourceexists")
    )


def reserve_pace(*, table=None, now=None):
    """Reserve one global slot using Azure Table ETag optimistic concurrency.

    Does not reserve a provider-day quota request. Call this *before* the
    existing shared daily budget reservation: when the daily budget fails,
    no paid call is made (at worst an unused pace slot).
    """
    if table is None:
        try:
            from ..services.admin_storage import _azure_table
            table = _azure_table(RATE_TABLE)
        except Exception as exc:
            raise SharedRateUnavailable("Global pace storage unavailable") from exc
    for attempt in range(MAX_RETRIES):
        when = float(now if now is not None else time.time())
        try:
            row = table.get_entity(partition_key=PARTITION, row_key=ROW)
        except Exception as exc:
            from ..services.admin_storage import _storage_not_found
            if _storage_not_found(exc):
                row = None
            else:
                raise SharedRateUnavailable("Global pace read failed") from exc
        try:
            prior = json.loads(row["payload"]) if row else None
            nxt = plan_pace(prior, now=when)
            entity = {"PartitionKey": PARTITION, "RowKey": ROW,
                      "payload": json.dumps(nxt, separators=(",", ":"))}
            if row is None:
                table.create_entity(entity)
            else:
                from azure.core import MatchConditions
                etag = getattr(row, "metadata", {}).get("etag")
                if not etag:
                    raise SharedRateUnavailable("Global pace CAS ETag missing")
                table.update_entity(entity, mode="merge", etag=etag,
                                    match_condition=MatchConditions.IfNotModified)
            return {"pace_schema": 1, "max_rps": MAX_RPS, "reserved_at": when}
        except (SharedRateBusy, SharedRateUnavailable):
            raise
        except Exception as exc:
            if not _conflict(exc):
                raise SharedRateUnavailable("Global pace CAS failed") from exc
            if attempt == MAX_RETRIES - 1:
                raise SharedRateUnavailable("Global pace CAS contention") from exc
            time.sleep(min(0.01 * (attempt + 1), 0.08))
    raise SharedRateUnavailable("Global pace exhausted")
