"""Serving readback canary: exact artifact hash, privacy, auth and no provider calls."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

import azure.functions as func
import pytest

from tbt.services.feed import empty_feed, serving_artifact_readback
from verify_live_serving_readback import validate, preflight_serving, main as verify_live_main


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

def test_both_deploy_paths_verify_live_serving_before_issuance():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    data = (root / ".github/workflows/data.yml").read_text(encoding="utf-8")
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    label = "Verify actual serving feed SHA and market counts from deployed Azure API"
    assert data.count(label) == 1
    assert data.index(label) < data.index("Confirm exactly deployed prediction publication")
    assert "if: env.BLINQ_SKIP_STALE_DEPLOY != 'true'" in data.split(label, 1)[1].split("Confirm exactly deployed prediction publication", 1)[0]
    assert "Verify actual deployed serving snapshot via worker canary" in ci
    assert ci.index("Verify actual deployed serving snapshot via worker canary") < ci.index("Replay existing TOP/VALUE CLV observations")
    for workflow in (data, ci):
        assert "python scripts/verify_live_serving_readback.py" in workflow
        assert "BLINQ_LIVE_WORKER_TOKEN: ${{ secrets.BLINQ_LIVE_WORKER_TOKEN }}" in workflow



def test_predeploy_current_day_guard_reuses_exact_server_validator(tmp_path):
    source = fixture(tmp_path)
    now = datetime(2026, 11, 6, 8, tzinfo=timezone.utc)
    report = preflight_serving(source, now=now)
    assert report["status"] == "ready"
    assert report["file_sha256"] == sha256(source.read_bytes()).hexdigest()
    assert report["betting_day"] == "2026-11-06"
    assert report["raw_counts"]["upcoming"] == 1
    assert report["paid_provider_requests"] == 0

    # Today can genuinely be quiet: 0 selections is not a reason to invent
    # a minimum count or block an otherwise valid prediction generation.
    quiet = empty_feed()
    quiet["ready"] = True
    quiet["generated_at"] = "2026-11-06T06:10:00Z"
    source.write_text(json.dumps(quiet), encoding="utf-8")
    assert all(count == 0 for count in
               preflight_serving(source, now=now)["raw_counts"].values())

    quiet["generated_at"] = "2026-11-05T06:10:00Z"
    source.write_text(json.dumps(quiet), encoding="utf-8")
    with pytest.raises(ValueError, match="not ready for the current betting day"):
        preflight_serving(source, now=now)

    quiet["generated_at"] = "2026-11-06T06:10:00Z"
    quiet["ready"] = False
    source.write_text(json.dumps(quiet), encoding="utf-8")
    with pytest.raises(ValueError, match="not ready for the current betting day"):
        preflight_serving(source, now=now)
    with pytest.raises(FileNotFoundError):
        preflight_serving(tmp_path / "absent.json", now=now)


def test_predeploy_cli_is_offline_without_worker_token_or_api(monkeypatch, capsys, tmp_path):
    import sys
    import verify_live_serving_readback as runner

    source = fixture(tmp_path)
    now = datetime(2026, 11, 6, 8, tzinfo=timezone.utc)
    original = runner.preflight_serving
    monkeypatch.setattr(runner, "preflight_serving",
                        lambda path: original(path, now=now))
    monkeypatch.delenv("BLINQ_LIVE_WORKER_TOKEN", raising=False)
    monkeypatch.setattr(runner, "urlopen",
                        lambda *_a, **_kw: (_ for _ in ()).throw(
                            AssertionError("Preflight must not touch HTTP")
                        ))
    monkeypatch.setattr(sys, "argv", [
        "verify_live_serving_readback.py", "--preflight-only",
        "--prepared-feed", str(source),
    ])
    verify_live_main()
    assert "BLINQ_SERVING_PREFLIGHT" in capsys.readouterr().out


def test_both_deploys_preflight_before_azure_upload():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path, deploy_name in (
        (".github/workflows/ci.yml", "Deploy BlinQ to Azure Static Web Apps"),
        (".github/workflows/data.yml", "Deploy refreshed feed and application"),
    ):
        yml = (root / path).read_text(encoding="utf-8")
        deploy = yml.index(deploy_name)
        preflight = yml.index("python scripts/verify_live_serving_readback.py --preflight-only")
        signed_readback = yml.index("python scripts/verify_live_serving_readback.py \\", deploy)
        confirm = yml.index("Confirm deployed prediction publication" if path.endswith("ci.yml")
                            else "Confirm exactly deployed prediction publication")
        assert preflight < deploy < signed_readback < confirm
        assert "--require-current" in yml[signed_readback:confirm]
        assert "python scripts/prepare_feed.py" in yml[:preflight]
    source = (root / "scripts/verify_live_serving_readback.py").read_text(encoding="utf-8")
    assert "if args.preflight_only:" in source
    assert "preflight_serving(Path(args.prepared_feed))" in source


def test_signed_live_canary_rejects_feed_that_aged_while_azure_uploaded(tmp_path):
    source = fixture(tmp_path)
    tomorrow = datetime(2026, 11, 7, 8, tzinfo=timezone.utc)
    deployed = serving_artifact_readback(source, now=tomorrow)
    assert deployed["stale"] is True
    # Existing read-only diagnostic deliberately remains permissive.
    assert validate(source.read_bytes(), deployed)["stale"] is True
    # Production issuance must NOT accept the exact same stale bytes after
    # crossing the 06:00 Bratislava day boundary during a slow deployment.
    with pytest.raises(ValueError, match="stale for the current betting day"):
        validate(source.read_bytes(), deployed, require_current=True)
    still_current = serving_artifact_readback(
        source, now=datetime(2026, 11, 6, 8, tzinfo=timezone.utc))
    assert validate(source.read_bytes(), still_current,
                    require_current=True)["status"] == "verified"
