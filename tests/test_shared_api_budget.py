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


def test_all_purposes_share_provider_day_pool_with_500_call_reserve():
    ledger = None
    for purpose, amount in (
        ("live", 3000),
        ("refresh", 3000),
        ("refresh", 2500),
        ("match", 2500),
        ("history", 2500),
        ("history", 1000),
    ):
        ledger, result = shared_budget.calculate(ledger, purpose, amount, now=NOW)

    assert result["provider_plan_limit"] == 15000
    assert result["global_limit"] == 14500
    assert result["global_spent"] == 14500
    assert result["global_remaining"] == 0
    assert result["reserved_provider_headroom"] == 500
    with pytest.raises(shared_budget.SharedBudgetExhausted):
        shared_budget.calculate(ledger, "refresh", 1, now=NOW)


def test_history_can_use_global_headroom_but_never_cross_provider_ceiling():
    ledger = None
    result = None
    for amount in (3000, 3000, 3000, 3000, 1500, 1000):
        ledger, result = shared_budget.calculate(ledger, "history", amount, now=NOW)
    assert result["spent"]["history"] == 14500
    assert result["global_spent"] == 14500
    assert result["global_remaining"] == 0
    assert result["reserved_provider_headroom"] == 500
    with pytest.raises(shared_budget.SharedBudgetExhausted):
        shared_budget.calculate(ledger, "history", 1, now=NOW)

def test_absolute_provider_hard_stop_between_1908_and_1910():
    # 2026-09-27 in Bratislava is UTC+2.
    for minute in (8, 9):
        with pytest.raises(shared_budget.SharedBudgetExhausted, match="19:08"):
            shared_budget.calculate(None, "live", 1,
                                    now=datetime(2026, 9, 27, 17, minute, tzinfo=timezone.utc))
    _, result = shared_budget.calculate(None, "live", 1,
                                        now=datetime(2026, 9, 27, 17, 10, tzinfo=timezone.utc))
    assert result["global_spent"] == 1
    assert result["global_remaining"] == 14499


def test_provider_day_resets_at_1910_bratislava():
    # 2026-09-27 is CEST, so 19:10 Europe/Bratislava == 17:10 UTC.
    before_reset = datetime(2026, 9, 27, 17, 7, tzinfo=timezone.utc)
    at_reset = datetime(2026, 9, 27, 17, 10, tzinfo=timezone.utc)

    ledger, result = shared_budget.calculate(None, "refresh", 1000, now=before_reset)
    assert result["global_spent"] == 1000

    ledger, result = shared_budget.calculate(ledger, "refresh", 1000, now=at_reset)
    assert result["global_spent"] == 1000
    assert result["global_remaining"] == 13250
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


def test_refresh_can_use_available_shared_pool_up_to_14500():
    ledger = None
    for amount in (3000, 3000, 3000, 3000, 2500):
        ledger, result = shared_budget.calculate(ledger, "refresh", amount, now=NOW)
    assert result["global_spent"] == 14500
    assert result["remaining"]["refresh"] == 0
    assert result["reserved_provider_headroom"] == 500
    with pytest.raises(shared_budget.SharedBudgetExhausted):
        shared_budget.calculate(ledger, "history", 1, now=NOW)


def test_real_environment_rapidapi_key_cannot_start_without_shared_ledger(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", "real-provider-key-for-test")
    for name in ("BLINQ_SHARED_API_BUDGET_URL", "BLINQ_SHARED_API_BUDGET_TOKEN",
                 "BLINQ_SHARED_API_BUDGET_PURPOSE"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(shared_budget.SharedBudgetUnavailable, match="Unmetered"):
        RapidTennisClient(Settings(rapidapi_key="real-provider-key-for-test"))
    # A metered caller remains supported (as do offline synthetic test keys).
    client = RapidTennisClient(
        Settings(rapidapi_key="real-provider-key-for-test"),
        request_budget=lambda *_args, **_kwargs: None,
    )
    client.close()


@pytest.mark.parametrize("override", ["0", "450", "499", "-1", "15000"])
def test_provider_reserve_cannot_be_weakened_with_environment_override(monkeypatch, override):
    from tbt.providers.rapidapi import _provider_request_reserve
    monkeypatch.setenv("BLINQ_PROVIDER_REQUEST_RESERVE", override)
    with pytest.raises(ConfigurationError, match="500"):
        _provider_request_reserve()


def test_provider_reserve_can_be_stricter_but_not_looser(monkeypatch):
    from tbt.providers.rapidapi import _provider_request_reserve
    monkeypatch.setenv("BLINQ_PROVIDER_REQUEST_RESERVE", "500")
    assert _provider_request_reserve() == 500
    monkeypatch.setenv("BLINQ_PROVIDER_REQUEST_RESERVE", "1500")
    assert _provider_request_reserve() == 1500


def test_provider_remaining_header_is_mandatory_for_paid_workers(monkeypatch):
    from tbt.providers.rapidapi import _require_provider_remaining_header
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RAPIDAPI_KEY", "fake-runner-secret")
    monkeypatch.setenv("BLINQ_REQUIRE_PROVIDER_RATE_LIMIT_HEADER", "false")
    assert _require_provider_remaining_header() is True
    monkeypatch.delenv("RAPIDAPI_KEY")
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    monkeypatch.setenv("FUNCTIONS_WORKER_RUNTIME", "python")
    assert _require_provider_remaining_header() is True


def test_binary_image_provider_request_requires_quota_header(monkeypatch):
    monkeypatch.setenv("BLINQ_REQUIRE_PROVIDER_RATE_LIMIT_HEADER", "true")
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    calls = []
    client = RapidTennisClient(Settings(rapidapi_key="test"))
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(
        lambda request: (
            calls.append(str(request.url))
            or httpx.Response(200, content=b"image-bytes",
                              headers={"content-type": "image/png"})
        )
    ))
    client._throttle = lambda: None
    try:
        with pytest.raises(RequestBudgetExceeded, match="remaining header missing"):
            client.player_image("123")
        assert client.request_count == 1
        assert len(calls) == 1
    finally:
        client.close()


def test_remote_budget_receipt_must_confirm_live_500_reserve_contract(monkeypatch):
    from tbt.providers.shared_budget import HttpReservation
    current = {
        "schema": 1,
        "window": "provider_day_19_10_europe_bratislava",
        "provider_plan_limit": 15000,
        "global_limit": 14500,
        "reserved_provider_headroom": 500,
        "global_spent": 12835,
        "global_remaining": 1665,
    }
    responses = [
        {"ok": True},  # An old API that says only "ok" is not safe.
        {"ok": True, "budget": {**current, "global_limit": 14250}},
        {"ok": True, "budget": {**current, "reserved_provider_headroom": 750}},
        {"ok": True, "budget": {**current, "global_remaining": 1700}},
        {"ok": True, "budget": current},
    ]
    reply = {"value": responses[0]}
    attempts = []
    def handler(request):
        attempts.append(str(request.url))
        return httpx.Response(200, json=reply["value"])

    monkeypatch.setattr(httpx, "Client", lambda *a, **k:
                        RealClient(transport=httpx.MockTransport(handler)))
    remote = HttpReservation(
        "https://quota.example.test/api/v1/internal/api-budget/reserve",
        "test-secret", "history",
    )
    try:
        for candidate in responses[:4]:
            reply["value"] = candidate
            with pytest.raises(shared_budget.SharedBudgetUnavailable,
                               match="contract mismatch"):
                remote()
        reply["value"] = responses[-1]
        remote()
        assert len(attempts) == len(responses)
    finally:
        remote.close()


def test_live_and_batch_workflows_enforce_identical_daily_limits():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    live = (root / ".github/workflows/live-radar.yml").read_text()
    data = (root / ".github/workflows/data.yml").read_text()
    history = (root / ".github/workflows/player-enrichment.yml").read_text()
    assert "budget['global_spent'] <= 14500 == budget['global_limit']" in live
    assert "budget['reserved_provider_headroom'] == 500" in live
    assert "BLINQ_REQUIRE_PROVIDER_RATE_LIMIT_HEADER: 'true'" in data
    assert "BLINQ_REQUIRE_PROVIDER_RATE_LIMIT_HEADER: 'true'" in history
    assert "unset BLINQ_SHARED_API_BUDGET_URL" not in data


@pytest.mark.parametrize("method", ["json", "image", "optional"])
def test_malformed_provider_remaining_header_blocks_further_calls(monkeypatch, method):
    monkeypatch.setenv("BLINQ_REQUIRE_PROVIDER_RATE_LIMIT_HEADER", "true")
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    sent = []
    def handler(request):
        sent.append(str(request.url))
        return httpx.Response(
            200, headers={"x-ratelimit-requests-remaining": "not-a-number",
                          "content-type": "image/png"},
            content=b"image" if method == "image" else b'{"events":[],"player":{}}',
        )
    client = RapidTennisClient(Settings(rapidapi_key="test"))
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(handler))
    client._throttle = lambda: None
    try:
        with pytest.raises(RequestBudgetExceeded, match="Invalid provider remaining header"):
            if method == "image":
                client.player_image("123")
            elif method == "optional":
                client.player_details("123")
            else:
                client.live_events()
        assert len(sent) == 1
        assert client.request_count == 1
    finally:
        client.close()


def test_no_direct_rapidapi_key_header_outside_canonical_client():
    """Prevent new unmetered HTTP clients from bypassing the single quota adapter."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    canonical = {root / "api/tbt/providers/rapidapi.py",
                 root / "api/tbt/providers/guarded_rapidapi.py"}
    unauthorized = []
    for parent in ("api", "scripts"):
        for path in (root / parent).rglob("*.py"):
            if path in canonical:
                continue
            source = path.read_text(encoding="utf-8").lower()
            if "x-rapidapi-key" in source or "x-rapidapi-host" in source:
                unauthorized.append(str(path.relative_to(root)))
    for path in (root / ".github/workflows").glob("*.yml"):
        source = path.read_text(encoding="utf-8").lower()
        if "x-rapidapi-key" in source or "x-rapidapi-host" in source:
            unauthorized.append(str(path.relative_to(root)))
    assert unauthorized == [], (
        "Unmetered direct RapidAPI headers outside approved adapters: "
        + ", ".join(sorted(unauthorized))
    )


def test_guarded_research_http_stops_on_provider_reserve(monkeypatch):
    from tbt.providers.guarded_rapidapi import GuardedRapidApiHttp
    class Budget:
        count = 0
        def __call__(self):
            self.count += 1
        def close(self):
            pass
    quota = Budget()
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={
            "x-ratelimit-requests-remaining": "500"
        }, json={})
    monkeypatch.setattr(httpx, "Client", lambda *a, **k:
                        RealClient(transport=httpx.MockTransport(handler)))
    with GuardedRapidApiHttp("test", "tennisapi1.p.rapidapi.com",
                             budget=quota) as client:
        with pytest.raises(ValueError, match="outside configured"):
            client.get("https://other.example.com/x")
        assert quota.count == 0
        with pytest.raises(RequestBudgetExceeded, match="reserve"):
            client.get("https://tennisapi1.p.rapidapi.com/api/tennis/live")
        with pytest.raises(RequestBudgetExceeded, match="reserve"):
            client.get("https://tennisapi1.p.rapidapi.com/api/tennis/live")
        assert quota.count == 1
        assert client.attempts == len(calls) == 1
