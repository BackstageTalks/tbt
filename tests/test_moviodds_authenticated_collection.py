"""Offline contract: MoviOdds provider key, 401/429 classification and archive cadence."""
from pathlib import Path
from urllib.error import HTTPError

import pytest

from tbt.services.moviodds_auth import MoviOddsAuthError, MoviOddsQuotaError
from tbt.services.moviodds_live import _fetch_board
from tbt.services.moviodds_stats import _get


def test_unkeyed_calls_do_not_reach_upstream(monkeypatch):
    monkeypatch.delenv("MOVIODDS_API_KEY", raising=False)
    called = []
    def forbid(*args, **kwargs):
        called.append(True)
        raise AssertionError("Unkeyed network call")
    with pytest.raises(MoviOddsAuthError, match="moviodds_api_key_missing"):
        _fetch_board(opener=forbid)
    with pytest.raises(MoviOddsAuthError, match="moviodds_api_key_missing"):
        _get("/results", params={"sport": "tennis"}, opener=forbid)
    assert not called


def test_secret_is_in_header_not_url(monkeypatch):
    monkeypatch.setenv("MOVIODDS_API_KEY", "fake-test-only")
    class Reply:
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, amount): return b'{"matches":[]}'
    def open_with_header(req, timeout):
        assert req.get_header("X-api-key") == "fake-test-only"
        assert "fake-test-only" not in req.full_url
        return Reply()
    assert _fetch_board(opener=open_with_header) == {"matches": []}


@pytest.mark.parametrize("status,error", [
    (401, MoviOddsAuthError),
    (429, MoviOddsQuotaError),
])
def test_unauthorized_and_quota_are_distinct(status, error):
    def reject(req, timeout):
        raise HTTPError(req.full_url, status, "provider error", {}, None)
    with pytest.raises(error):
        _get("/results", params={"sport": "tennis"}, opener=reject, api_key="fake-test-only")


def test_final_capture_and_archive_order_is_safe():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/match-status.yml").read_text()
    collect = workflow.split("- name: Capture finalized MoviOdds", 1)[1].split("- name: Dispatch completed Telegram", 1)[0]
    archive = workflow.split("- name: Archive completed MoviOdds", 1)[1].split("- name: Dispatch guarded CDB", 1)[0]
    assert "MOVIODDS_FINAL_NOT_DUE_04_16_UTC" in collect
    assert 'if [[ "$hour" != "05" ]]' in archive
    assert "X-MoviOdds-API-Key: $MOVIODDS_API_KEY" in collect
    assert "if: ${{ false }}" in workflow
    api = (root / "api/function_app.py").read_text()
    route = api.split("def internal_moviodds_stats_worker(req):", 1)[1].split("@app.route(",1)[0]
    assert route.index("_live_worker_token_ok(req)") < route.index('get("X-MoviOdds-API-Key")')
