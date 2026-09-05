from dataclasses import replace
from datetime import date

import httpx
import pytest

from tbt.config import Settings
from tbt.providers.budget import RequestBudgetExceeded
from tbt.providers.rapidapi import RapidTennisClient
from tbt.errors import ProviderError


def test_bad_envelopes_are_not_treated_as_empty_history():
    with pytest.raises(ProviderError):
        RapidTennisClient._response_rows({"message": "not authorized"}, "events")
    assert RapidTennisClient._response_rows({"data": {"events": []}}, "events") == []


def client(handler):
    cfg = replace(Settings(), rapidapi_key="test")
    provider = RapidTennisClient(cfg)
    provider.client.close()
    provider.client = httpx.Client(transport=httpx.MockTransport(handler))
    provider._throttle = lambda: None
    return provider


def test_denied_budget_sends_no_upstream_request():
    calls = []
    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(200, json={})
    provider = client(handler)
    def deny(*args, **kwargs):
        raise RequestBudgetExceeded("test exhausted")
    provider.request_budget = deny
    with pytest.raises(RequestBudgetExceeded):
        provider._get("/api/tennis/event/123")
    assert calls == []
    assert provider.request_count == 0
    provider.client.close()


def test_every_retry_reserves_and_respects_run_limit(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(200, json=True) if request.url.host == "db.invalid" else httpx.Response(503)
    monkeypatch.setattr("tbt.providers.rapidapi.time.sleep", lambda _: None)
    provider = client(handler)
    provider.request_limit = 2
    provider.request_budget = lambda *a, **kw: calls.append("reservation")
    with pytest.raises(RequestBudgetExceeded):
        provider._get("/api/tennis/event/123")
    assert calls == ["reservation", "tennisapi1.p.rapidapi.com"] * 2
    assert provider.request_count == 2
    provider.client.close()


def test_settlement_uses_only_requested_days(match_factory):
    provider = RapidTennisClient.__new__(RapidTennisClient)
    days = []
    def matches(tour, day, historical):
        days.append(day)
        assert historical
        return [match_factory(str(day), "A", "B", "A", day=day.day)]
    provider.matches_for_day = matches
    results = provider.historical_period("atp", date(2025, 1, 2), date(2025, 1, 4))
    assert len(results) == 3
    assert days == [date(2025, 1, d) for d in (2, 3, 4)]
