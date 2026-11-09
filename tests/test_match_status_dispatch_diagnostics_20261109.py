"""No-paid-call regression for the externally dispatched Match Status failure path."""
from __future__ import annotations

import json
import re
from pathlib import Path

import azure.functions as func
import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_match_status_never_dispatches_deleted_or_nonmanual_workflow():
    source = (WORKFLOWS / "match-status.yml").read_text(encoding="utf-8")
    destinations = re.findall(r"(?m)^\s*gh workflow run\s+([a-z0-9_-]+\.yml)\b", source)
    assert len(destinations) >= 9, "Unexpectedly missing Match Status dispatch coverage"
    assert "model-711-forward-blind.yml" not in source, "Retired 7.1.1 dispatch returned HTTP 422"
    for name in destinations:
        path = WORKFLOWS / name
        assert path.is_file(), f"Dispatch target was removed: {name}"
        workflow = path.read_text(encoding="utf-8")
        assert re.search(r"(?m)^  workflow_dispatch:\s*$", workflow), (
            f"Dispatch target lacks workflow_dispatch: {name}"
        )
    # External scheduler remains authoritative. No extra native schedule introduced.
    assert "vars.BLINQ_NATIVE_SCHEDULES_ENABLED == 'true'" in source


def _req(secret: str) -> func.HttpRequest:
    return func.HttpRequest(
        method="POST",
        url="http://localhost/api/v1/internal/match-status-worker",
        headers={"X-Blinq-Worker-Token": secret} if secret else {},
        body=b"",
    )


@pytest.mark.parametrize("phase", [
    "read_feed", "load_snapshot", "capture_issued_rollover",
])
def test_worker_returns_only_safe_stage_and_never_spends_quota_on_preflight_error(
    monkeypatch, phase,
):
    import function_app as api

    monkeypatch.setenv("BLINQ_LIVE_WORKER_TOKEN", "test-worker-only")
    incident = []
    monkeypatch.setattr(
        api, "record_system_event", lambda *args, **kwargs: incident.append(kwargs)
    )
    monkeypatch.setattr(
        api, "RapidTennisClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Provider must not be called before preflight completes")
        ),
    )

    def invalid(*_args, **_kwargs):
        raise ValueError("SECRET_AND_PRIVATE_SOURCE_MUST_NOT_LEAK")

    monkeypatch.setattr(
        api, "_read_feed_with_confirmed_aces_ou",
        invalid if phase == "read_feed" else lambda: {"schema": 1},
    )
    monkeypatch.setattr(
        api, "load_match_status_snapshot",
        invalid if phase == "load_snapshot" else lambda: {},
    )
    monkeypatch.setattr(api, "load_authority", lambda day: None)
    monkeypatch.setattr(
        api, "confirmed_rollover_rows",
        invalid if phase == "capture_issued_rollover" else lambda *args, **kwargs: [],
    )
    response = api.internal_match_status_worker(_req("test-worker-only"))
    assert response.status_code == 503
    raw = response.get_body().decode("utf-8")
    result = json.loads(raw)
    assert result == {
        "error": "match_status_worker_failed",
        "detail": "ValueError",
        "phase": phase,
    }
    assert "SECRET_AND_PRIVATE" not in raw
    assert incident and incident[0]["details"] == {
        "error": "ValueError", "phase": phase,
    }


def test_worker_never_exposes_debug_phase_without_worker_secret(monkeypatch):
    import function_app as api

    monkeypatch.setenv("BLINQ_LIVE_WORKER_TOKEN", "test-worker-only")
    response = api.internal_match_status_worker(_req(""))
    assert response.status_code == 403
    assert "phase" not in response.get_body().decode("utf-8")
