"""Verified gzip web rollout: authorization, rollback, raw-JSON parity."""
import gzip
import json
from pathlib import Path

import function_app as api

from test_feed_lazy_authorized_kpis_20261111 import _stub_authenticated_feed


class Request:
    def __init__(self, encoding="gzip", **params):
        self.headers = {"Accept-Encoding": encoding}
        self.params = params


def test_gzip_requires_explicit_flag_but_not_diagnostic_trace(monkeypatch):
    calls = _stub_authenticated_feed(monkeypatch)
    normal = api.feed(Request())
    assert normal["results"] == [{"event_id": "settled"}]
    assert "__blinq_feed_stage_ms" not in normal

    compressed = api.feed(Request(blinq_feed_gzip="1"))
    assert compressed.status_code == 200
    assert compressed.headers["Content-Encoding"] == "gzip"
    assert compressed.headers["Vary"] == "Accept-Encoding"
    assert compressed.headers["Cache-Control"] == "no-store"
    assert "__blinq_feed_stage_ms" not in json.loads(gzip.decompress(compressed.get_body()))
    decoded = json.loads(gzip.decompress(compressed.get_body()))
    assert decoded == json.loads(json.dumps(normal, ensure_ascii=False, allow_nan=False))
    assert calls == [("settled",), ("settled",)]


def test_gzip_rollback_and_encoding_negotiation_are_fail_closed(monkeypatch):
    calls = _stub_authenticated_feed(monkeypatch)
    normal = api.feed(Request(blinq_feed_gzip="0"))
    no_encoding = api.feed(Request("br, deflate", blinq_feed_gzip="1"))
    disabled = api.feed(Request("gzip;q=0", blinq_feed_gzip="1"))
    assert isinstance(normal, dict)
    assert no_encoding == normal
    assert disabled == normal
    assert calls == [("settled",)] * 3


def test_authenticated_web_uses_gzip_with_explicit_opt_out_and_original_fallback():
    root = Path(__file__).resolve().parents[1]
    auth = (root / "web/auth.js").read_text(encoding="utf-8")
    app = (root / "api/function_app.py").read_text(encoding="utf-8")
    feed = app[app.index('@app.route(route="v1/feed", methods=["GET"])'):
               app.index('@app.route(route="v1/internal/clv-snapshot"')]
    assert "let useGzip = true;" in auth
    assert "get('blinq_feed_gzip') !== '0'" in auth
    assert "request(url + '&blinq_feed_gzip=1')" in auth
    assert "if (!useGzip) return request()" in auth
    assert "return request();" in auth
    assert "if ([401, 403].includes(Number(error?.status))) throw error" in auth
    assert 'if (compressed && Array.isArray(compressed.upcoming) && Array.isArray(compressed.results)' in auth
    assert 'data["__blinq_feed_stage_ms"] = trace_marks' in feed
    assert '"blinq_feed_gzip") or "") == "1" and _feed_gzip_acceptable(req)' in feed
    assert 'return response(data)' in feed
