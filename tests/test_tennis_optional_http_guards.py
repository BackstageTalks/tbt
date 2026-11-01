"""Regression tests for optional Tennis API requests sharing guarded HTTP controls."""
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from tbt.providers.rapidapi import RapidTennisClient
from tbt.providers.budget import RequestBudgetExceeded
from tbt.errors import ProviderError


def client_for(monkeypatch, responses, attempts=2):
    client = RapidTennisClient.__new__(RapidTennisClient)
    client.cfg = SimpleNamespace(
        rapidapi_base_url="https://test.invalid",
        rapidapi_key="synthetic",
        rapidapi_host="test.invalid",
    )
    client.client = Mock()
    client.client.get.side_effect = [
        httpx.Response(status, json=body, headers=headers,
                       request=httpx.Request("GET", "https://test.invalid/optional"))
        if status not in (204, 404) else
        httpx.Response(status, headers=headers,
                       request=httpx.Request("GET", "https://test.invalid/optional"))
        for status, body, headers in responses
    ]
    client.retry_attempts = attempts
    client.request_budget = None
    client.request_limit = 14500
    client.request_count = 0
    client.rate_limit_remaining = None
    client._last_request_at = 0.0
    client._min_request_interval = 0.0
    monkeypatch.delenv("BLINQ_REQUIRE_PROVIDER_RATE_LIMIT_HEADER", raising=False)
    monkeypatch.delenv("FUNCTIONS_WORKER_RUNTIME", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("BLINQ_API_AUTOFILL_STOP_AT_UTC", raising=False)
    monkeypatch.setattr("tbt.providers.rapidapi.time.sleep", lambda _: None)
    return client


def test_optional_204_and_404_are_absent_without_retry(monkeypatch):
    for status in (204, 404):
        client = client_for(monkeypatch, [(status, {}, {})])
        assert client._get_optional_json("/optional") == {}
        assert client.request_count == 1
        assert client.client.get.call_count == 1


def test_optional_429_is_retried_and_accounted(monkeypatch):
    client = client_for(monkeypatch, [
        (429, {"error": "throttle"}, {"Retry-After": "0"}),
        (200, {"player": 4}, {}),
    ])
    assert client._get_optional_json("/optional") == {"player": 4}
    assert client.request_count == 2
    assert client.client.get.call_count == 2


def test_optional_respects_batch_cutoff_before_paid_call(monkeypatch):
    client = client_for(monkeypatch, [(200, {}, {})])
    monkeypatch.setenv("BLINQ_API_AUTOFILL_STOP_AT_UTC", "2020-01-01T00:00:00Z")
    with pytest.raises(RequestBudgetExceeded, match="cutoff"):
        client._get_optional_json("/optional")
    assert client.request_count == 0
    client.client.get.assert_not_called()


def test_nonoptional_404_still_fails(monkeypatch):
    client = client_for(monkeypatch, [(404, {}, {})])
    with pytest.raises(ProviderError, match="404"):
        client._get("/required")
    assert client.request_count == 1


def test_optional_preserves_provider_reserve(monkeypatch):
    client = client_for(monkeypatch, [(200, {}, {})])
    client.rate_limit_remaining = 500
    with pytest.raises(RequestBudgetExceeded, match="reserve"):
        client._get_optional_json("/optional")
    assert client.request_count == 0
