"""No-paid capability readback and fail-closed URL safety."""
from urllib.error import HTTPError

import pytest

import verify_private_tennis_cache_ready as gate


BUDGET = "https://blinq.azurestaticapps.net/api/v1/internal/api-budget/reserve"
CACHE = "https://blinq.azurestaticapps.net/api/v1/internal/tennis-raw-cache"


class Reply:
    status = 200
    def __init__(self, body=b'{"ok":true,"status":"miss"}'):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size):
        return self.body[:size]


def test_approved_origin_is_exact_and_secret_safe():
    assert gate.cache_endpoint(BUDGET) == CACHE
    assert gate.cache_endpoint(BUDGET, CACHE) == CACHE
    with pytest.raises(gate.CacheCapabilityError):
        gate.cache_endpoint(BUDGET, "https://attacker.test/api/v1/internal/tennis-raw-cache")
    with pytest.raises(gate.CacheCapabilityError):
        gate.cache_endpoint("http://blinq.azurestaticapps.net/api/v1/internal/api-budget/reserve")


def test_readback_requires_live_store_and_worker_token():
    assert gate.verify_cache_service(CACHE, "synthetic", opener=lambda req, timeout: Reply())
    with pytest.raises(gate.CacheCapabilityError):
        gate.verify_cache_service(CACHE, "", opener=lambda req, timeout: Reply())
    with pytest.raises(gate.CacheCapabilityError):
        gate.verify_cache_service(CACHE, "synthetic",
                                  opener=lambda req, timeout: Reply(b'{"ok":true,"status":"busy"}'))


def test_undeployed_route_does_not_activate_or_spend():
    def missing(req, timeout):
        raise HTTPError(req.full_url, 404, "missing", {}, None)
    assert gate.verify_cache_service(CACHE, "synthetic", opener=missing) is False
    with pytest.raises(gate.CacheCapabilityError):
        gate.verify_cache_service(CACHE, "synthetic", explicit=True, opener=missing)


def test_verified_cache_sets_pacing_and_raw_env_only_after_readback(monkeypatch, tmp_path):
    envfile = tmp_path / "github-env"
    envfile.write_text("")
    monkeypatch.setenv("GITHUB_ENV", str(envfile))
    monkeypatch.setenv("BLINQ_SHARED_API_BUDGET_URL", BUDGET)
    monkeypatch.setenv("BLINQ_SHARED_API_BUDGET_TOKEN", "synthetic")
    monkeypatch.delenv("BLINQ_TENNIS_RAW_CACHE_URL", raising=False)
    monkeypatch.setattr(gate, "verify_cache_service", lambda *args, **kw: True)
    gate.main()
    assert envfile.read_text() == (
        f"BLINQ_TENNIS_RAW_CACHE_URL={CACHE}\n"
        "BLINQ_SHARED_RPS_REQUIRED=true\n"
    )


def test_private_cache_redirect_cannot_forward_worker_token():
    from urllib.request import Request
    request = Request(CACHE, headers={"X-Blinq-Worker-Token": "worker-secret"})
    handler = gate.DenyWorkerTokenRedirect()
    assert handler.redirect_request(request, None, 302, "Found", {},
                                    "https://attacker.test/collect") is None
