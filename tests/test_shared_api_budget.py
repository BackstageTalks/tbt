from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading

import httpx
import pytest

from tbt.config import Settings
from tbt.errors import ConfigurationError
from tbt.providers import shared_budget
from tbt.providers.budget import RequestBudgetExceeded
from tbt.providers.rapidapi import RapidTennisClient

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def test_all_purposes_share_provider_day_pool_with_3_percent_reserve():
    ledger = None
    for purpose, amount in (
        ("live", 3000),
        ("refresh", 3000),
        ("refresh", 2500),
        ("match", 2500),
        ("history", 2500),
        ("history", 1050),
    ):
        ledger, result = shared_budget.calculate(ledger, purpose, amount, now=NOW)

    assert result["provider_plan_limit"] == 15000
    assert result["global_limit"] == 14550
    assert result["global_spent"] == 14550
    assert result["global_remaining"] == 0
    assert result["reserved_provider_headroom"] == 450
    with pytest.raises(shared_budget.SharedBudgetExhausted):
        shared_budget.calculate(ledger, "refresh", 1, now=NOW)


def test_history_can_use_global_headroom_but_never_cross_ninety_seven_percent():
    ledger = None
    result = None
    for amount in (3000, 3000, 3000, 3000, 1500, 1050):
        ledger, result = shared_budget.calculate(ledger, "history", amount, now=NOW)
    assert result["spent"]["history"] == 14550
    assert result["global_spent"] == 14550
    assert result["global_remaining"] == 0
    assert result["reserved_provider_headroom"] == 450
    with pytest.raises(shared_budget.SharedBudgetExhausted):
        shared_budget.calculate(ledger, "history", 1, now=NOW)

def test_provider_day_resets_at_1910_bratislava():
    # 2026-09-27 is CEST, so 19:10 Europe/Bratislava == 17:10 UTC.
    before_reset = datetime(2026, 9, 27, 17, 9, tzinfo=timezone.utc)
    at_reset = datetime(2026, 9, 27, 17, 10, tzinfo=timezone.utc)

    ledger, result = shared_budget.calculate(None, "refresh", 1000, now=before_reset)
    assert result["global_spent"] == 1000

    ledger, result = shared_budget.calculate(ledger, "refresh", 1000, now=at_reset)
    assert result["global_spent"] == 1000
    assert result["global_remaining"] == 13550
    assert result["window"] == "provider_day_19_10_europe_bratislava"


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
                        {"live": 10, "match": 10, "refresh": 10, "history": 10})
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


def test_batch_provider_rate_can_be_raised_to_six_rps_without_changing_default(monkeypatch):
    monkeypatch.delenv("BLINQ_RAPIDAPI_MAX_RPS", raising=False)
    default_client = RapidTennisClient(Settings(rapidapi_key="test"))
    try:
        assert default_client._min_request_interval == pytest.approx(0.66)
    finally:
        default_client.close()

    monkeypatch.setenv("BLINQ_RAPIDAPI_MAX_RPS", "6")
    batch_client = RapidTennisClient(Settings(rapidapi_key="test"))
    try:
        assert batch_client._min_request_interval == pytest.approx(1 / 6)
    finally:
        batch_client.close()


def test_batch_provider_rate_rejects_values_above_six_rps(monkeypatch):
    monkeypatch.setenv("BLINQ_RAPIDAPI_MAX_RPS", "6.1")
    with pytest.raises(ConfigurationError):
        RapidTennisClient(Settings(rapidapi_key="test"))


def test_provider_header_guard_stops_at_configured_reserve(monkeypatch):
    monkeypatch.setenv("BLINQ_PROVIDER_REQUEST_RESERVE", "1500")
    monkeypatch.setenv("BLINQ_REQUIRE_PROVIDER_RATE_LIMIT_HEADER", "true")
    client = RapidTennisClient(Settings(rapidapi_key="test"))
    calls = []
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(
        lambda req: (
            calls.append(req.url)
            or httpx.Response(
                200,
                headers={"x-ratelimit-requests-remaining": "1500"},
                json={"events": []},
            )
        )
    ))
    client._throttle = lambda: None
    client.request_limit = 10000
    try:
        assert client.live_events() == []
        assert client.request_count == 1
        with pytest.raises(RequestBudgetExceeded, match="keeping 1500"):
            client.live_events()
        assert client.request_count == 1
        assert len(calls) == 1
    finally:
        client.close()


def test_provider_header_guard_fails_closed_when_remaining_header_missing(monkeypatch):
    monkeypatch.setenv("BLINQ_PROVIDER_REQUEST_RESERVE", "1500")
    monkeypatch.setenv("BLINQ_REQUIRE_PROVIDER_RATE_LIMIT_HEADER", "true")
    client = RapidTennisClient(Settings(rapidapi_key="test"))
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"events": []})
    ))
    client._throttle = lambda: None
    try:
        with pytest.raises(RequestBudgetExceeded, match="remaining header missing"):
            client.live_events()
        assert client.request_count == 1
    finally:
        client.close()
