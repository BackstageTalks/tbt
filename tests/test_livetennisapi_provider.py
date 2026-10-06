import httpx
import pytest

from tbt.errors import ConfigurationError
from tbt.providers.budget import RequestBudgetExceeded
from tbt.providers.livetennisapi import LiveTennisApiClient


def _client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return LiveTennisApiClient(
        "secret-test-key",
        client=http,
        usage_ttl_seconds=3600,
        **kwargs,
    )


def test_missing_key_fails_closed(monkeypatch):
    monkeypatch.delenv("LIVE_TENNIS_API_KEY", raising=False)
    with pytest.raises(ConfigurationError):
        LiveTennisApiClient()


def test_usage_is_quota_exempt_and_does_not_increment_local_calls():
    def handler(request):
        assert request.url.path.endswith("/usage")
        assert request.headers["X-API-Key"] == "secret-test-key"
        return httpx.Response(
            200,
            json={
                "tier": "free",
                "limits": {"per_day": 100, "per_minute": 30},
                "today": {"calls": 7, "errors": 0, "remaining_day": 93},
            },
        )

    client = _client(handler)
    assert client.remaining_day() == 93
    assert client.request_count == 0


def test_live_matches_checks_usage_then_spends_one_call():
    seen = []

    def handler(request):
        seen.append((request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/usage"):
            return httpx.Response(
                200,
                json={
                    "tier": "free",
                    "limits": {"per_day": 100, "per_minute": 30},
                    "today": {"calls": 0, "errors": 0, "remaining_day": 100},
                },
            )
        assert request.url.path.endswith("/matches")
        return httpx.Response(200, json={"data": [{"id": 123}, "bad"]})

    client = _client(handler, max_calls=5, daily_reserve=20)
    assert client.live_matches(limit=5) == [{"id": 123}]
    assert client.request_count == 1
    assert client.remaining_day() == 99
    assert seen[1][1] == {"status": "live", "limit": "5"}


def test_daily_reserve_blocks_billable_call():
    def handler(request):
        assert request.url.path.endswith("/usage")
        return httpx.Response(
            200,
            json={
                "tier": "free",
                "limits": {"per_day": 100, "per_minute": 30},
                "today": {"calls": 80, "errors": 0, "remaining_day": 20},
            },
        )

    client = _client(handler, daily_reserve=20)
    with pytest.raises(RequestBudgetExceeded, match="daily reserve"):
        client.live_matches()
    assert client.request_count == 0


def test_per_process_cap_blocks_second_billable_call():
    def handler(request):
        if request.url.path.endswith("/usage"):
            return httpx.Response(
                200,
                json={
                    "tier": "free",
                    "limits": {"per_day": 100, "per_minute": 30},
                    "today": {"calls": 0, "errors": 0, "remaining_day": 100},
                },
            )
        return httpx.Response(200, json={"data": []})

    client = _client(handler, max_calls=1)
    client.live_matches()
    with pytest.raises(RequestBudgetExceeded, match="per-process"):
        client.upcoming_matches()


def test_match_score_validates_id_without_provider_call():
    called = False

    def handler(request):
        nonlocal called
        called = True
        return httpx.Response(500)

    client = _client(handler)
    with pytest.raises(ValueError):
        client.match_score("../bad")
    assert called is False
