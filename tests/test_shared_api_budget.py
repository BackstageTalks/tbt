from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading

import httpx
import pytest

from tbt.config import Settings
from tbt.providers import shared_budget
from tbt.providers.budget import RequestBudgetExceeded
from tbt.providers.rapidapi import RapidTennisClient

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def test_independent_live_and_morning_caps_preserve_emergency_headroom():
    ledger = None
    ledger, result = shared_budget.calculate(ledger, "live", 2500, now=NOW)
    assert result["remaining"]["live"] == 0
    assert result["global_spent"] == 2500
    with pytest.raises(shared_budget.SharedBudgetExhausted):
        shared_budget.calculate(ledger, "live", 1, now=NOW)
    ledger, result = shared_budget.calculate(ledger, "refresh", 750, now=NOW)
    assert result["remaining"]["refresh"] == 0
    assert result["global_remaining"] == 8750
    for chunk in (3000, 3000, 1750):
        ledger, result = shared_budget.calculate(ledger, "history", chunk, now=NOW)
    ledger, result = shared_budget.calculate(ledger, "match", 1000, now=NOW)
    assert result["global_spent"] == 12000
    assert result["global_remaining"] == 0
    assert result["reserved_provider_headroom"] == 3000


def test_rolling_24_hours_keeps_boundary_bucket_conservatively():
    ledger, _ = shared_budget.calculate(None, "live", 1, now=NOW)
    with pytest.raises(shared_budget.SharedBudgetExhausted):
        shared_budget.calculate(ledger, "live", 2500, now=NOW + timedelta(hours=24))
    ledger, result = shared_budget.calculate(
        ledger, "live", 2500,
        now=NOW + timedelta(hours=24, minutes=5),
    )
    assert result["spent"]["live"] == 2500


def test_corrupt_ledger_and_bad_request_fail_closed():
    with pytest.raises(shared_budget.SharedBudgetUnavailable):
        shared_budget.calculate({"schema": 99}, "live", 1, now=NOW)
    with pytest.raises(ValueError):
        shared_budget.calculate(None, "live", True, now=NOW)
    with pytest.raises(ValueError):
        shared_budget.calculate(None, "typo", 1, now=NOW)


class Conflict(Exception):
    def __init__(self, code=412):
        super().__init__("etag changed")
        self.status_code = code


class VersionedRow(dict):
    def __init__(self, values, version):
        super().__init__(values)
        self.metadata = {"etag": version}


class AtomicFakeTable:
    def __init__(self):
        self.row = None
        self.version = 0
        self.lock = threading.Lock()

    def get_entity(self, *, partition_key, row_key):
        with self.lock:
            if self.row is None:
                raise KeyError("not created")
            return VersionedRow(self.row, self.version)

    def create_entity(self, entity):
        with self.lock:
            if self.row is not None:
                raise Conflict(409)
            self.row = dict(entity)
            self.version += 1

    def update_entity(self, entity, *, mode, etag, match_condition):
        with self.lock:
            if int(etag) != self.version:
                raise Conflict()
            self.row.update(entity)
            self.version += 1


def test_parallel_reservations_never_overspend(monkeypatch):
    table = AtomicFakeTable()
    monkeypatch.setattr(shared_budget, "GLOBAL_CEILING", 10)
    monkeypatch.setattr(shared_budget, "PURPOSE_CAPS",
                        {"live": 10, "match": 1000, "refresh": 750, "history": 7750})
    monkeypatch.setattr(shared_budget, "MAX_RETRIES", 40)

    def attempt(_):
        try:
            return shared_budget.reserve("live", now=NOW, table=table)
        except shared_budget.SharedBudgetExhausted:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(24)))
    assert len([value for value in outcomes if value is not None]) == 10
    assert shared_budget.status(now=NOW, table=table)["global_spent"] == 10
    assert table.version == 10


def test_budget_storage_outage_blocks_paid_provider_calls():
    calls = []

    class BrokenStorage:
        def get_entity(self, **kwargs):
            raise OSError("storage offline")

    cfg = Settings(rapidapi_key="test")
    client = RapidTennisClient(
        cfg, request_budget=lambda *a, **kw: shared_budget.reserve(
            "live", now=NOW, table=BrokenStorage()
        ),
    )
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(
        lambda req: (calls.append(req.url) or httpx.Response(200, json={}))
    ))
    client._throttle = lambda: None
    try:
        with pytest.raises(shared_budget.SharedBudgetUnavailable):
            client.live_events()
        assert client.request_count == 0
        assert calls == []
    finally:
        client.close()


def test_environment_requires_all_remote_credentials(monkeypatch):
    monkeypatch.setenv("BLINQ_SHARED_API_BUDGET_URL",
                       "https://example.test/api/v1/internal/api-budget/reserve")
    monkeypatch.delenv("BLINQ_SHARED_API_BUDGET_TOKEN", raising=False)
    monkeypatch.setenv("BLINQ_SHARED_API_BUDGET_PURPOSE", "history")
    with pytest.raises(shared_budget.SharedBudgetUnavailable):
        shared_budget.from_environment()


def test_remote_429_stops_before_provider_request(monkeypatch):
    from tbt.providers.shared_budget import HttpReservation
    calls = []

    def handler(req):
        calls.append(req.url.host)
        return httpx.Response(429, json={"error": "api_budget_exhausted"})

    monkeypatch.setattr(httpx, "Client", lambda *a, **kw:
                        RealClient(transport=httpx.MockTransport(handler)))
    budget = HttpReservation(
        "https://quota.example.test/api/v1/internal/api-budget/reserve",
        "test-secret", "live",
    )
    with pytest.raises(shared_budget.SharedBudgetExhausted):
        budget()


RealClient = httpx.Client
