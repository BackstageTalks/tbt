"""Serving readback canary: exact artifact hash, privacy, auth and no provider calls."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

import azure.functions as func
import pytest

from tbt.services.feed import empty_feed, serving_artifact_readback
from verify_live_serving_readback import validate


def fixture(tmp_path):
    feed = empty_feed()
    feed["ready"] = True
    feed["generated_at"] = "2026-11-06T06:10:00Z"
    event = {
        "event_id": "123",
        "scheduled_at": "2026-11-06T13:30:00Z",
        "player1": {"id": "a", "name": "Alpha"},
        "player2": {"id": "b", "name": "Beta"},
        "surface": "hard",
    }
    feed["upcoming"] = [event]
    feed["top_daily_picks"] = [event]
    path = tmp_path / "feed.json"
    path.write_text(json.dumps(feed, ensure_ascii=False), encoding="utf-8")
    return path


def test_exact_serving_bytes_and_public_day_counts_without_member_fields(tmp_path):
    source = fixture(tmp_path)
    now = datetime(2026, 11, 6, 8, tzinfo=timezone.utc)
    report = serving_artifact_readback(source, now=now)
    assert report["ready"] is True
    assert report["stale"] is False
    assert report["betting_day"] == "2026-11-06"
    assert report["file_sha256"] == sha256(source.read_bytes()).hexdigest()
    assert report["bytes"] == source.stat().st_size
    assert report["raw_counts"]["upcoming"] == 1
    assert report["visible_counts"]["top_daily_picks"] == 1
    assert report["visible_counts"]["results"] == 0
    assert validate(source.read_bytes(), report)["status"] == "verified"
    assert not any(key in report for key in ("account", "rows", "selection", "user_id", "odds"))


def test_canary_rejects_wrong_source_even_when_http_ok_and_counts_match(tmp_path):
    source = fixture(tmp_path)
    report = serving_artifact_readback(source, now=datetime(2026, 11, 6, 8, tzinfo=timezone.utc))
    corrupt = dict(report, file_sha256="0" * 64)
    with pytest.raises(ValueError, match="SHA-256"):
        validate(source.read_bytes(), corrupt)
    corrupt = dict(report, ready=False)
    with pytest.raises(ValueError, match="not ready"):
        validate(source.read_bytes(), corrupt)
    corrupt = dict(report, raw_counts={**report["raw_counts"], "upcoming": 0})
    with pytest.raises(ValueError, match="count mismatch"):
        validate(source.read_bytes(), corrupt)


def test_serving_readback_fails_closed_for_missing_or_malformed_file(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        serving_artifact_readback(missing)
    bad = fixture(tmp_path)
    content = json.loads(bad.read_text(encoding="utf-8"))
    content["ace_picks"] = {"malformed": True}
    bad.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid serving market rows"):
        serving_artifact_readback(bad)


def test_protected_endpoint_never_returns_hash_or_counts_without_worker_secret(monkeypatch, tmp_path):
    import function_app as api

    source = fixture(tmp_path)
    monkeypatch.setattr(api, "FEED", source)
    monkeypatch.setenv("BLINQ_LIVE_WORKER_TOKEN", "test-private-worker-token")
    missing = func.HttpRequest(
        method="GET", url="http://localhost/api/v1/internal/serving-readback",
        headers={}, body=b"",
    )
    denied = api.internal_serving_readback(missing)
    assert denied.status_code == 403
    assert "file_sha256" not in denied.get_body().decode()
    wrong = func.HttpRequest(
        method="GET", url="http://localhost/api/v1/internal/serving-readback",
        headers={"X-Blinq-Worker-Token": "incorrect"}, body=b"",
    )
    assert api.internal_serving_readback(wrong).status_code == 403
    authorized = func.HttpRequest(
        method="GET", url="http://localhost/api/v1/internal/serving-readback",
        headers={"X-Blinq-Worker-Token": "test-private-worker-token"}, body=b"",
    )
    response = api.internal_serving_readback(authorized)
    assert response.status_code == 200
    result = json.loads(response.get_body())
    assert result["file_sha256"] == sha256(source.read_bytes()).hexdigest()
    assert result["ready"] is True
