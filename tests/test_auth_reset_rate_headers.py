"""Anonymous reset rate limiter must not trust caller-controlled forwarding headers."""
from types import SimpleNamespace

import function_app as api


def _reset(monkeypatch):
    api._AUTH_EMAIL_RATE_BUCKETS.clear()
    api._AUTH_EMAIL_RATE_GLOBAL.clear()
    monkeypatch.setattr(api.time, "monotonic", lambda: 1200.0)


def test_untrusted_forwarding_headers_cannot_rotate_client_bucket(monkeypatch):
    _reset(monkeypatch)
    for i in range(25):
        req = SimpleNamespace(headers={
            "X-Forwarded-For": f"203.0.113.{i + 1}",
            "X-Client-IP": f"198.51.100.{i + 1}",
        })
        assert api._auth_email_request_allowed(req)
    # Without a trusted platform header, no attacker-chosen per-client buckets.
    assert api._AUTH_EMAIL_RATE_BUCKETS == {}
    assert len(api._AUTH_EMAIL_RATE_GLOBAL) == 25


def test_trusted_platform_ip_remains_rate_limited(monkeypatch):
    _reset(monkeypatch)
    for i in range(api._AUTH_EMAIL_RATE_MAX_REQUESTS):
        req = SimpleNamespace(headers={
            "X-Azure-ClientIP": "2001:0db8::1",
            "X-Forwarded-For": f"203.0.113.{i + 1}",
        })
        assert api._auth_email_request_allowed(req)
    assert not api._auth_email_request_allowed(SimpleNamespace(headers={
        "X-Azure-ClientIP": "2001:db8::1",
        "X-Forwarded-For": "198.51.100.220",
    }))
    assert len(api._AUTH_EMAIL_RATE_BUCKETS) == 1


def test_invalid_platform_ip_cannot_create_extra_buckets(monkeypatch):
    _reset(monkeypatch)
    for value in ("203.0.113.1, 203.0.113.2", "not-ip", ""):
        assert api._auth_email_request_allowed(SimpleNamespace(headers={
            "X-Azure-ClientIP": value,
            "X-Forwarded-For": "8.8.8.8",
        }))
    assert api._AUTH_EMAIL_RATE_BUCKETS == {}


def test_global_limit_applies_when_trusted_header_is_missing(monkeypatch):
    _reset(monkeypatch)
    req = SimpleNamespace(headers={"X-Forwarded-For": "203.0.113.1"})
    for _ in range(api._AUTH_EMAIL_RATE_GLOBAL_MAX_REQUESTS):
        assert api._auth_email_request_allowed(req)
    assert not api._auth_email_request_allowed(req)
    assert api._AUTH_EMAIL_RATE_BUCKETS == {}
