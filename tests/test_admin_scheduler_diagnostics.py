import json
from datetime import datetime, timezone

import function_app


class Request:
    headers = {}


def _json_response(http_response):
    return json.loads(http_response.get_body().decode("utf-8"))


def test_admin_diagnostics_uses_runtime_budget_caps_and_exposes_external_scheduler_health(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()

    monkeypatch.setattr(function_app, "_admin_user", lambda req: ({"id": "admin"}, None))
    monkeypatch.setattr(
        function_app,
        "admin_storage_diagnostics",
        lambda: {"backend": "azure", "services": {"premium_info": True}},
    )
    monkeypatch.setattr(
        function_app,
        "media_storage_diagnostics",
        lambda: {"configured": True, "available": True},
    )
    monkeypatch.setattr(
        function_app,
        "push_storage_diagnostics",
        lambda: {"enabled": True, "storage_available": True},
    )
    monkeypatch.setattr(function_app, "load_runtime_ui_config", lambda: {})
    monkeypatch.setattr(function_app, "inactivity_policy", lambda runtime: {"enabled": False})
    monkeypatch.setattr(function_app, "smtp_diagnostics", lambda settings: {"configured": True})
    monkeypatch.setattr(function_app, "load_account_worker_status", lambda: {})
    monkeypatch.setattr(
        function_app,
        "load_live_worker_status",
        lambda: {
            "updated_at": now,
            "scanned_at": now,
            "live_events": 2,
            "candidates": 1,
            "signals": 1,
            "new_alerts": 0,
        },
    )
    monkeypatch.setattr(
        function_app,
        "load_match_status_snapshot",
        lambda: {
            "updated_at": now,
            "tracked": 20,
            "due": 3,
            "checked": 3,
            "provider_requests": 4,
            "provider_errors": {},
            "degraded": False,
            "budget_paused": False,
        },
    )
    monkeypatch.setattr(
        function_app,
        "read_feed",
        lambda path: {
            "ready": True,
            "generated_at": now,
            "upcoming": [],
            "results": [],
            "model": {"version": "test"},
        },
    )
    monkeypatch.setattr(function_app, "visible_feed", lambda feed: {"stale": False})
    monkeypatch.setattr(function_app, "_feed_asset_health", lambda feed: {})
    monkeypatch.setattr(
        function_app,
        "shared_api_budget_status",
        lambda: {
            "global_spent": 10800,
            "global_limit": 13500,
            "spent": {
                "live": 2400,
                "match": 2000,
                "refresh": 4400,
                "history": 2000,
            },
        },
    )
    monkeypatch.setattr(function_app, "list_users", lambda *args, **kwargs: [{"id": "u"}])
    monkeypatch.setattr(
        function_app,
        "list_system_events",
        lambda **kwargs: {
            "hours": 24,
            "counts": {"info": 0, "warning": 0, "error": 0},
            "items": [],
            "available": True,
        },
    )
    monkeypatch.setattr(function_app, "auth_provider", lambda settings: "firebase")
    monkeypatch.setenv("BLINQ_LIVE_WORKER_TOKEN", "configured")
    monkeypatch.setattr(function_app.settings, "firebase_project_id", "p")
    monkeypatch.setattr(function_app.settings, "firebase_client_email", "a@example.com")
    monkeypatch.setattr(function_app.settings, "firebase_private_key", "key")

    payload = _json_response(function_app.admin_diagnostics(Request()))

    alerts = {row["name"]: row["percent"] for row in payload["api_budget"]["alerts"]}
    assert alerts == {
        "global": 80,
        "live": 80,
        "match": 80,
        "refresh": 80,
        "history": 80,
    }

    live = payload["live_worker"]
    assert live["scheduler_owner"] == "external"
    assert live["expected_cadence_seconds"] == 300
    assert live["healthy"] is True
    assert live["next_due_at"]

    status = payload["match_status_worker"]
    assert status["scheduler_owner"] == "external"
    assert status["expected_cadence_seconds"] == 1800
    assert status["healthy"] is True
    assert status["tracked"] == 20
    assert status["due"] == 3
    assert status["checked"] == 3
    assert status["provider_requests"] == 4
    assert status["next_due_at"]
    assert payload["services"]["match_status_worker"] is True
