"""Reservations survive cancelled Actions runs; no Supabase dependency."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone

from tbt.providers.budget import RequestBudgetExceeded


def reserve_allocation(ledger, requested, now=None, run_id="local", purpose="history"):
    now = now or datetime.now(timezone.utc)
    if purpose not in {"history", "refresh"}:
        raise ValueError("Unknown reservation purpose")
    if not 1 <= requested <= 15000:
        raise ValueError("Request allocation must be 1..15000")
    if ledger and ledger.get("schema") != 1:
        raise ValueError("Unsupported request ledger schema")
    active = []
    for entry in ledger.get("reservations", []):
        expires = datetime.fromisoformat(entry["expires_at"])
        if expires.tzinfo is None or not 1 <= int(entry["requests"]) <= 15000:
            raise ValueError("Invalid request ledger entry")
        if expires > now:
            active.append(entry)
    ceiling = 12000 if purpose == "history" else 15000
    available = max(0, ceiling - sum(int(e["requests"]) for e in active))
    granted = min(requested, available)
    if granted:
        # A run lasts at most three hours. 28h protects the rolling 24h quota
        # even for requests issued near the end of an interrupted run.
        active.append({"run_id": run_id, "purpose": purpose, "requests": granted,
                       "created_at": now.isoformat(),
                       "expires_at": (now + timedelta(hours=28)).isoformat()})
    return {"schema": 1, "reservations": active}, granted


class LocalRequestBudget:
    """Persistent rolling limit for local runs, plus a strict three-hour deadline."""
    def __init__(self, path, limit=15000, duration_seconds=10800):
        self.connection = sqlite3.connect(str(path), timeout=30)
        self.connection.execute("CREATE TABLE IF NOT EXISTS requests (at REAL NOT NULL)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS requests_time ON requests(at)")
        self.limit = limit
        self.deadline = time.monotonic() + duration_seconds

    def __call__(self, client=None, cfg=None, *, enrichment=False):
        if time.monotonic() >= self.deadline:
            raise RequestBudgetExceeded("Run deadline reached; save progress and resume")
        now = time.time()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute("DELETE FROM requests WHERE at < ?", (now - 86400,))
            count = self.connection.execute("SELECT count(*) FROM requests").fetchone()[0]
            if count >= self.limit:
                raise RequestBudgetExceeded("Local rolling 24h allowance exhausted")
            self.connection.execute("INSERT INTO requests VALUES (?)", (now,))
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def close(self):
        self.connection.close()
