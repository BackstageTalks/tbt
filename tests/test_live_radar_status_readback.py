"""Read-only worker GET verifies persisted heartbeat and exact shared quota."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import function_app


class Request:
    def __init__(self, token="secret"):
        self.headers = {"X-Blinq-Worker-Token": token}


def payload(reply):
    return json.loads(reply.get_body())


def budget():
    return {
        "provider_plan_limit": 15000,
        "reserved_provider_headroom": 450,
        "global_limit": 14550,
        "global_spent": 2100,
        "spent": {"live": 300, "match": 0, "refresh": 0, "history": 1800},
        "purpose_limits": {"live": 3000},
        "next_reset_utc": "2026-10-11T17:10:00+00:00",
    }


def setup(monkeypatch, status=None, *, shared=None):
    monkeypatch.setenv("BLINQ_LIVE_WORKER_TOKEN", "secret")
    now = datetime.now(timezone.utc).isoformat()
    record = status if status is not None else {
        "scanned_at": now, "last_success_at": now,
        "updated_at": now, "budget_paused": False,
    }
    monkeypatch.setattr(function_app, "load_live_worker_status", lambda: record)
    monkeypatch.setattr(function_app, "shared_api_budget_status", lambda: shared or budget())


def test_authorized_readback_is_fresh_and_makes_no_scan(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(function_app, "_run_live_radar", lambda **kwargs: (_ for _ in ()).throw(AssertionError("paid scan")))
    response = function_app.internal_live_radar_status(Request())
    value = payload(response)
    assert response.status_code == 200 and value["ok"] is True
    assert value["heartbeat"]["fresh"] is True
    assert value["budget"]["global_limit"] == 14550
    assert value["budget"]["live_spent"] == 300


def test_bad_token_and_missing_token_do_not_reveal_budget(monkeypatch):
    setup(monkeypatch)
    for token in ("bad", ""):
        response = function_app.internal_live_radar_status(Request(token))
        assert response.status_code == 403
        assert "budget" not in payload(response)


def test_stale_heartbeat_and_budget_corruption_fail_closed(monkeypatch):
    age = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    setup(monkeypatch, {"last_success_at": age, "scanned_at": age})
    assert function_app.internal_live_radar_status(Request()).status_code == 503
    setup(monkeypatch, shared={**budget(), "global_spent": 14551})
    assert payload(function_app.internal_live_radar_status(Request()))["error"] == "api_budget_invalid"


def test_unavailable_persistent_heartbeat_fails_closed(monkeypatch):
    setup(monkeypatch, {})
    monkeypatch.setattr(function_app, "load_live_worker_status", lambda: None)
    assert payload(function_app.internal_live_radar_status(Request()))["error"] == "live_heartbeat_missing"
