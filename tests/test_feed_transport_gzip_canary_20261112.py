"""Diagnostic-only feed transport: safe by default and faithful JSON bytes."""
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import function_app as api


def _request(header="", **params):
    return SimpleNamespace(headers={"Accept-Encoding": header}, params=params)


@pytest.mark.parametrize("header,allowed", [
    ("gzip, deflate, br", True),
    ("br, gzip;q=0.5", True),
    ("gzip;q=0", False),
    ("gzip;q=0.0", False),
    ("br", False),
    ("", False),
    ("gzip;q=garbage", False),
])
def test_compression_is_only_used_when_client_accepts_it(header, allowed):
    assert api._feed_gzip_acceptable(_request(header)) is allowed


def test_canary_gzip_response_preserves_exact_json_and_never_caches():
    payload = {
        "upcoming": [{"event_id": f"x{i}", "players": ["Šimon", "Mária"]} for i in range(200)],
        "results": [{"event_id": "z", "market_publications": [{"market": "aces"}]}],
        "account": {"plan": "elite"},
        "entitlements": {"results": True},
    }
    reply = api._gzip_feed_response(payload)
    assert reply.status_code == 200
    assert reply.headers["Content-Encoding"] == "gzip"
    assert reply.headers["Vary"] == "Accept-Encoding"
    assert reply.headers["Cache-Control"] == "no-store"
    assert reply.headers["X-Content-Type-Options"] == "nosniff"
    expected = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    assert gzip.decompress(reply.get_body()) == expected
    assert len(reply.get_body()) < len(expected) // 3


def test_real_feed_handler_supports_canary_but_ordinary_path_is_unchanged(monkeypatch):
    from test_feed_lazy_authorized_kpis_20261111 import _stub_authenticated_feed
    calls = _stub_authenticated_feed(monkeypatch)
    ordinary = api.feed(_request("gzip", blinq_feed_trace="1"))
    assert ordinary["results"] == [{"event_id": "settled"}]
    assert calls == [("settled",)]
    compressed = api.feed(_request("gzip", blinq_feed_trace="1", blinq_feed_gzip="1"))
    assert compressed.headers["Content-Encoding"] == "gzip"
    hydrated = json.loads(gzip.decompress(compressed.get_body()))
    assert hydrated["results"] == ordinary["results"]
    assert hydrated["dashboard_kpi_cards"] == json.loads(json.dumps(ordinary["dashboard_kpi_cards"]))
    assert hydrated["__blinq_feed_stage_ms"][-1][0] == "clv_complete"
    assert calls == [("settled",), ("settled",)]
    no_encoding = api.feed(_request("br", blinq_feed_trace="1", blinq_feed_gzip="1"))
    assert isinstance(no_encoding, dict)
    assert no_encoding["results"] == ordinary["results"]


def test_anonymous_cannot_request_gzip_payload(monkeypatch):
    monkeypatch.setattr(api, "_verified_user", lambda _req: None)
    monkeypatch.setattr(api, "response", lambda data, status=200: (data, status))
    assert api.feed(_request("gzip", blinq_feed_trace="1", blinq_feed_gzip="1")) == (
        {"error": "unauthorized"}, 401
    )


def test_diagnostics_are_opt_in_without_altering_normal_transport():
    root = Path(__file__).resolve().parents[1]
    src = (root / "api/function_app.py").read_text()
    auth = (root / "web/auth.js").read_text()
    app = (root / "web/app.js").read_text()
    feed = src[src.index('@app.route(route="v1/feed", methods=["GET"])'):
               src.index('@app.route(route="v1/internal/clv-snapshot"')]
    assert 'if trace_started is not None:' in feed
    assert '_feed_gzip_acceptable(req)' in feed
    assert 'return _gzip_feed_response(data)' in feed
    assert 'return response(data)' in feed
    assert "const url = traced ? '/api/v1/feed?blinq_feed_trace=1' : '/api/v1/feed';" in auth
    assert "gzipCanary = traced && new URLSearchParams(location.search).get('blinq_feed_gzip') === '1'" in auth
    assert "return request();" in auth
    assert "return requestWithSafeFallback();" in auth
    assert "performance.getEntriesByType('resource')" in app
    assert "Feed sieť: TTFB " in app
    assert "window.alert(message)" in app
