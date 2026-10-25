"""Local RapidAPI safeguards on the UTC 17:09 provider-day calendar.

These conservative helpers never bypass the authoritative Azure ETag budget.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone

from tbt.providers.budget import RequestBudgetExceeded
from tbt.providers.shared_budget import (
    DAILY_STOP_MINUTE, GLOBAL_CEILING, RESET_HOUR, RESET_MINUTE,
)


def provider_day_start(now: datetime) -> datetime:
    """UTC subscription-day boundary, independent of Bratislava DST."""
    if now.tzinfo is None:
        raise ValueError("Provider budget time must be timezone-aware")
    utc = now.astimezone(timezone.utc)
    start = utc.replace(hour=RESET_HOUR, minute=RESET_MINUTE,
                        second=0, microsecond=0)
    return start if utc >= start else start - timedelta(days=1)


def next_provider_reset(now: datetime) -> datetime:
    return provider_day_start(now) + timedelta(days=1)


def _check_rollover(now: datetime) -> None:
    utc = now.astimezone(timezone.utc)
    if utc.hour == RESET_HOUR and DAILY_STOP_MINUTE <= utc.minute <= RESET_MINUTE:
        raise RequestBudgetExceeded("Provider rollover safety stop: 17:07–17:10 UTC")


def reserve_allocation(ledger, requested, now=None, run_id="local", purpose="history"):
    now = now if now is not None else datetime.now(timezone.utc)
    start = provider_day_start(now)
    _check_rollover(now)
    if purpose not in {"history", "refresh"}:
        raise ValueError("Unknown reservation purpose")
    if isinstance(requested, bool) or not isinstance(requested, int) or not 1 <= requested <= GLOBAL_CEILING:
        raise ValueError(f"Request allocation must be 1..{GLOBAL_CEILING}")
    if ledger is None:
        ledger = {"schema": 1, "reservations": []}
    if not isinstance(ledger, dict) or ledger.get("schema") != 1:
        raise ValueError("Unsupported request ledger schema")
    entries = ledger.get("reservations")
    if not isinstance(entries, list):
        raise ValueError("Invalid request reservations")
    active = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid request ledger entry")
        try:
            created = datetime.fromisoformat(entry["created_at"])
            expires = datetime.fromisoformat(entry["expires_at"])
            amount = entry["requests"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid request ledger entry") from exc
        if (created.tzinfo is None or expires.tzinfo is None
                or isinstance(amount, bool) or not isinstance(amount, int)
                or not 1 <= amount <= GLOBAL_CEILING or created > now):
            raise ValueError("Invalid request ledger entry")
        # Legacy 28h reservations are not carried over the provider reset.
        if created >= start and expires > now:
            active.append(entry)
    available = max(0, GLOBAL_CEILING - sum(e["requests"] for e in active))
    granted = min(requested, available)
    if granted:
        # Cancellation cannot free reserved capacity before the next reset.
        active.append({"run_id": run_id, "purpose": purpose, "requests": granted,
                       "created_at": now.isoformat(),
                       "expires_at": next_provider_reset(now).isoformat()})
    return {"schema": 1, "reservations": active}, granted


class LocalRequestBudget:
    """Secondary SQLite cap per UTC provider day, plus a three-hour deadline."""

    def __init__(self, path, limit=GLOBAL_CEILING, duration_seconds=10800):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= GLOBAL_CEILING:
            raise ValueError(f"Local provider-day cap must be 1..{GLOBAL_CEILING}")
        self.connection = sqlite3.connect(str(path), timeout=30)
        self.connection.execute("CREATE TABLE IF NOT EXISTS requests (at REAL NOT NULL)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS requests_time ON requests(at)")
        self.limit = limit
        self.deadline = time.monotonic() + duration_seconds

    def __call__(self, client=None, cfg=None, *, enrichment=False):
        if time.monotonic() >= self.deadline:
            raise RequestBudgetExceeded("Run deadline reached; save progress and resume")
        now = datetime.fromtimestamp(time.time(), tz=timezone.utc)
        _check_rollover(now)
        start_epoch = provider_day_start(now).timestamp()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute("DELETE FROM requests WHERE at < ?", (start_epoch,))
            count = self.connection.execute("SELECT count(*) FROM requests").fetchone()[0]
            if count >= self.limit:
                raise RequestBudgetExceeded("Local UTC provider-day allowance exhausted")
            self.connection.execute("INSERT INTO requests VALUES (?)", (now.timestamp(),))
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def close(self):
        self.connection.close()
