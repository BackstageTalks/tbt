"""Anonymous banner rate limiting must not trust request-supplied client_id."""
from types import SimpleNamespace

import function_app as api


def _clear(monkeypatch):
    api._BANNER_RATE_BUCKETS.clear()
    api._BANNER_RATE_GLOBAL.clear()
    monkeypatch.setattr(api.time, "monotonic", lambda: 2000.0)


def test_randomized_client_ids_do_not_rotate_trusted_ip_bucket(monkeypatch):
    _clear(monkeypatch)
    req = SimpleNamespace(headers={"X-Azure-SocketIP": "2001:db8::1", "X-Azure-ClientIP": "203.0.113.44"})
    for i in range(api._BANNER_RATE_MAX_EVENTS):
        assert api._banner_event_allowed({"client_id": f"arbitrary-{i}"}, req)
    assert not api._banner_event_allowed({"client_id": "last-try"}, req)
    assert len(api._BANNER_RATE_BUCKETS) == 1
    assert len(api._BANNER_RATE_GLOBAL) == api._BANNER_RATE_MAX_EVENTS


def test_spoofed_forwarding_headers_do_not_rotate_bucket(monkeypatch):
    _clear(monkeypatch)
    for i in range(api._BANNER_RATE_MAX_EVENTS):
        req = SimpleNamespace(headers={
            "X-Azure-SocketIP": "192.0.2.1",
            "X-Azure-ClientIP": f"198.51.100.{i+1}",
            "X-Forwarded-For": f"203.0.113.{i+1}",
            "X-Client-IP": f"198.51.100.{i+1}",
        })
        assert api._banner_event_allowed({"client_id": str(i)}, req)
    assert not api._banner_event_allowed(
        {"client_id": "new"},
        SimpleNamespace(headers={"X-Azure-SocketIP": "192.0.2.1", "X-Azure-ClientIP": "203.0.113.1",
                                 "X-Forwarded-For": "1.2.3.4"}),
    )


def test_missing_or_invalid_platform_ip_keeps_global_cap(monkeypatch):
    _clear(monkeypatch)
    for i in range(api._BANNER_RATE_GLOBAL_MAX_EVENTS):
        req = SimpleNamespace(headers={
            "X-Azure-SocketIP": "bad" if i % 2 else "",
            "X-Azure-ClientIP": f"198.51.100.{i % 250 + 1}",
            "X-Forwarded-For": f"203.0.113.{i % 250 + 1}",
        })
        assert api._banner_event_allowed({"client_id": f"rotate-{i}"}, req)
    assert not api._banner_event_allowed(
        {"client_id": "rotate-again"}, SimpleNamespace(headers={})
    )
    assert api._BANNER_RATE_BUCKETS == {}


def test_event_route_passes_actual_request_to_guard():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "api" / "function_app.py").read_text()
    assert "_banner_event_allowed(payload, req)" in source


def test_client_ip_spoofing_without_edge_socket_uses_only_global_cap(monkeypatch):
    _clear(monkeypatch)
    for i in range(80):
        req = SimpleNamespace(headers={
            "X-Azure-ClientIP": f"192.0.2.{i % 250 + 1}",
            "X-Forwarded-For": f"203.0.113.{i % 250 + 1}",
        })
        assert api._banner_event_allowed({"client_id": f"id-{i}"}, req)
    assert api._BANNER_RATE_BUCKETS == {}
    assert len(api._BANNER_RATE_GLOBAL) == 80
