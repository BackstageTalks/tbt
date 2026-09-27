"""Conservative, shared rolling Tennis RapidAPI budget.

One ETag-protected Azure Table / Firestore row is the source of truth across
Azure Functions and GitHub Actions. Five-minute buckets retain an extra bucket
at the 24h boundary to avoid ever undercounting a rolling 24-hour window.
Reserve BEFORE every billable attempt, including retries; never refund an
ambiguous network failure. Missing storage must fail closed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time
from typing import Any

from .budget import RequestBudgetExceeded

WINDOW_SLOTS = 288  # 24 hours * 12 five-minute buckets
SLOT_SECONDS = 300
GLOBAL_CEILING = 12000  # 15,000 plan minus 3,000 emergency headroom
PURPOSE_CAPS = {"live": 2500, "match": 250, "refresh": 750, "history": 8500}
PURPOSE_INDEX = {name: pos + 1 for pos, name in enumerate(PURPOSE_CAPS)}
TABLE = "BlinQApiBudget"
PARTITION = "rapidapi"
ROW = "rolling24h-v1"
MAX_RETRIES = 12


class SharedBudgetUnavailable(RequestBudgetExceeded):
    """No verified global reservation was possible; do not spend."""


class SharedBudgetExhausted(RequestBudgetExceeded):
    """The shared ceiling or this purpose's allocation was reached."""


def _now_slot(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Budget times must be timezone-aware")
    return int(now.timestamp()) // SLOT_SECONDS


def _normalized(raw: object, slot: int) -> list[list[int]]:
    if raw is None:
        return []
    if not isinstance(raw, dict) or raw.get("schema") != 1:
        raise SharedBudgetUnavailable("Unknown API budget ledger schema")
    buckets = raw.get("buckets", [])
    if not isinstance(buckets, list):
        raise SharedBudgetUnavailable("Invalid budget ledger")
    values: dict[int, list[int]] = {}
    for entry in buckets:
        if not isinstance(entry, list) or len(entry) != 5:
            raise SharedBudgetUnavailable("Invalid budget bucket")
        numbers = [int(v) for v in entry]
        minute_slot = numbers[0]
        if any(v < 0 for v in numbers[1:]) or minute_slot > slot:
            raise SharedBudgetUnavailable("Corrupt or future-dated budget bucket")
        # Retain one extra bucket at the rolling boundary (fail safe).
        if minute_slot >= slot - WINDOW_SLOTS:
            if minute_slot in values:
                raise SharedBudgetUnavailable("Duplicate budget bucket")
            values[minute_slot] = numbers
    return [values[key] for key in sorted(values)]


def _summary(buckets: list[list[int]], slot: int) -> dict[str, Any]:
    spent = {name: sum(item[idx] for item in buckets)
             for name, idx in PURPOSE_INDEX.items()}
    total = sum(spent.values())
    return {
        "schema": 1,
        "window": "rolling_24h_conservative_5min",
        "updated_slot": slot,
        "global_limit": GLOBAL_CEILING,
        "global_spent": total,
        "global_remaining": max(0, GLOBAL_CEILING - total),
        "reserved_provider_headroom": 3000,
        "spent": spent,
        "remaining": {name: max(0, PURPOSE_CAPS[name] - spent[name])
                      for name in PURPOSE_CAPS},
    }


def calculate(ledger: dict | None, purpose: str, requested: int = 1,
              *, now: datetime | None = None) -> tuple[dict, dict]:
    """Pure reservation planning; no paid API or storage requests."""
    if purpose not in PURPOSE_CAPS:
        raise ValueError("Unknown budget purpose")
    if isinstance(requested, bool) or not isinstance(requested, int) or not 1 <= requested <= 3000:
        raise ValueError("Requests must be an integer from 1 to 3000")
    slot = _now_slot(now)
    buckets = _normalized(ledger, slot)
    before = _summary(buckets, slot)
    if (before["global_remaining"] < requested
            or before["remaining"][purpose] < requested):
        raise SharedBudgetExhausted("Shared Tennis API budget exhausted")
    if not buckets or buckets[-1][0] != slot:
        buckets.append([slot, 0, 0, 0, 0])
    buckets[-1][PURPOSE_INDEX[purpose]] += requested
    after = _summary(buckets, slot)
    return {"schema": 1, "buckets": buckets}, after


def _conflict(exc: Exception) -> bool:
    code = getattr(exc, "status_code", None)
    name = type(exc).__name__.lower()
    return code in (409, 412) or any(
        marker in name for marker in ("conflict", "precondition", "resourceexists")
    )


def reserve(purpose: str, requested: int = 1, *, now: datetime | None = None,
            table: Any = None) -> dict:
    """Atomic reservation in the same durable store used by BlinQ admin.

    Table may be injected in tests. Retries only on optimistic write races,
    never on uncertain transport failures.
    """
    if purpose not in PURPOSE_CAPS:
        raise ValueError("Unknown budget purpose")
    if table is None:
        from ..services.admin_storage import _table
        try:
            table = _table(TABLE)
        except Exception as exc:
            raise SharedBudgetUnavailable("API budget storage unavailable") from exc
    for attempt in range(MAX_RETRIES):
        try:
            entity = table.get_entity(partition_key=PARTITION, row_key=ROW)
        except Exception as exc:
            from ..services.admin_storage import _storage_not_found
            if not _storage_not_found(exc):
                raise SharedBudgetUnavailable("API budget read failed") from exc
            entity = None
        try:
            ledger = json.loads(entity["payload"]) if entity else None
            new_ledger, result = calculate(ledger, purpose, requested, now=now)
            updated = {"PartitionKey": PARTITION, "RowKey": ROW,
                       "payload": json.dumps(new_ledger, separators=(",", ":"))}
            if entity is None:
                table.create_entity(updated)
            else:
                from azure.core import MatchConditions
                etag = getattr(entity, "metadata", {}).get("etag")
                if etag is None:
                    raise SharedBudgetUnavailable("Budget store lacks conditional writes")
                table.update_entity(
                    updated, mode="merge", etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                )
            return result
        except SharedBudgetExhausted:
            raise
        except Exception as exc:
            if isinstance(exc, SharedBudgetUnavailable):
                raise
            if not _conflict(exc):
                raise SharedBudgetUnavailable("API budget reservation failed") from exc
            # ETag conflict: re-read and retry; never overwrite another reserve.
            if attempt + 1 == MAX_RETRIES:
                raise SharedBudgetUnavailable("API budget contention") from exc
            time.sleep(min(0.025 * (attempt + 1), 0.15))
    raise SharedBudgetUnavailable("API budget contention")


def status(*, now: datetime | None = None, table: Any = None) -> dict:
    if table is None:
        from ..services.admin_storage import _table
        try:
            table = _table(TABLE)
        except Exception as exc:
            raise SharedBudgetUnavailable("API budget storage unavailable") from exc
    try:
        row = table.get_entity(partition_key=PARTITION, row_key=ROW)
    except Exception as exc:
        from ..services.admin_storage import _storage_not_found
        if _storage_not_found(exc):
            return _summary([], _now_slot(now))
        raise SharedBudgetUnavailable("API budget read failed") from exc
    try:
        return _summary(_normalized(json.loads(row["payload"]), _now_slot(now)), _now_slot(now))
    except (ValueError, KeyError, TypeError) as exc:
        raise SharedBudgetUnavailable("API budget ledger unreadable") from exc


class HttpReservation:
    """Per-attempt reservation for GitHub Actions jobs without storage keys."""

    def __init__(self, endpoint: str, token: str, purpose: str) -> None:
        if not endpoint.startswith("https://") or "/api/v1/internal/api-budget/reserve" not in endpoint:
            raise ValueError("Shared budget endpoint must be HTTPS")
        if not token or purpose not in PURPOSE_CAPS:
            raise ValueError("Missing budget credential or invalid purpose")
        self.endpoint = endpoint
        self.token = token
        self.purpose = purpose

    def __call__(self, client=None, cfg=None, *, enrichment=False) -> None:
        import httpx
        try:
            with httpx.Client(timeout=7.0) as transport:
                response = transport.post(
                    self.endpoint,
                    headers={"X-Blinq-Worker-Token": self.token},
                    json={"purpose": self.purpose, "requests": 1},
                )
            if response.status_code == 429:
                raise SharedBudgetExhausted("Shared Tennis API budget exhausted")
            if response.status_code != 200 or response.json().get("ok") is not True:
                raise SharedBudgetUnavailable("Shared API budget verification failed")
        except RequestBudgetExceeded:
            raise
        except Exception as exc:
            raise SharedBudgetUnavailable("Cannot reserve shared API capacity") from exc


def from_environment():
    endpoint = os.getenv("BLINQ_SHARED_API_BUDGET_URL", "").strip()
    token = os.getenv("BLINQ_SHARED_API_BUDGET_TOKEN", "").strip()
    purpose = os.getenv("BLINQ_SHARED_API_BUDGET_PURPOSE", "").strip()
    if not (endpoint or token or purpose):
        return None
    # Partially configured jobs must never fall back to unmetered calls.
    if not all((endpoint, token, purpose)):
        raise SharedBudgetUnavailable("Incomplete shared API budget configuration")
    return HttpReservation(endpoint, token, purpose)
