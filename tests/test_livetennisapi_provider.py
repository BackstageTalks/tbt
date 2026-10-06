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


def test_paid_plan_allows_controlled_700_call_cap():
    def handler(request):
        assert request.url.path.endswith("/usage")
        return httpx.Response(
            200,
            json={
                "tier": "basic",
                "limits": {"per_day": 1000, "per_minute": 120},
                "today": {"calls": 50, "errors": 0, "remaining_day": 950},
            },
        )

    client = _client(handler, max_calls=700, daily_reserve=200)
    assert client.max_calls == 700
    assert client.daily_reserve == 200
    assert client.remaining_day() == 950


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


def test_paid_history_endpoints_request_complete_point_basis():
    seen = []

    def handler(request):
        seen.append((request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/usage"):
            return httpx.Response(
                200,
                json={
                    "tier": "basic",
                    "limits": {"per_day": 1000, "per_minute": 120},
                    "today": {"calls": 0, "errors": 0, "remaining_day": 1000},
                },
            )
        if request.url.path.endswith("/history/coverage"):
            return httpx.Response(200, json={"data": [], "meta": {"as_of": "2026-10-06"}})
        if request.url.path.endswith("/history/matches"):
            return httpx.Response(200, json={"data": [], "meta": {"count": 0}})
        if request.url.path.endswith("/history/matches/77"):
            return httpx.Response(
                200,
                json={
                    "match": {"id": 77},
                    "tape": [],
                    "meta": {"points": {"available_complete": True}},
                },
            )
        return httpx.Response(404)

    client = _client(handler, max_calls=10, daily_reserve=200)
    assert client.history_coverage()["meta"]["as_of"] == "2026-10-06"
    assert client.history_matches(
        from_date="2026-01-01",
        to_date="2026-10-05",
        tour="wta",
        points_complete=True,
        limit=100,
        offset=200,
    )["meta"]["count"] == 0
    assert client.history_tape(77, complete=True)["match"]["id"] == 77

    list_call = next(row for row in seen if row[0].endswith("/history/matches"))
    assert list_call[1]["from"] == "2026-01-01"
    assert list_call[1]["to"] == "2026-10-05"
    assert list_call[1]["tour"] == "wta"
    assert list_call[1]["draw"] == "singles"
    assert list_call[1]["points_complete"] == "true"
    assert list_call[1]["limit"] == "100"
    assert list_call[1]["offset"] == "200"
    tape_call = next(row for row in seen if row[0].endswith("/history/matches/77"))
    assert tape_call[1] == {"points": "complete"}
