"""No-provider, no-member protected serving feed readback regression tests."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tbt.services.feed import empty_feed
from tbt.services.serving_feed_readback import SERVING_COUNT_KEYS, serving_feed_readback
from scripts.verify_deployed_serving_feed import verify_readback

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)
GENERATED = "2026-11-06T06:10:00+00:00"


def candidate(tmp_path, *, generated=GENERATED, ready=True, with_picks=True):
    target = tmp_path / "feed.json"
    payload = empty_feed()
    payload["ready"] = ready
    payload["generated_at"] = generated
    if with_picks:
        fixture = {
            "event_id": "readback-event",
            "scheduled_at": "2026-11-06T19:00:00+00:00",
            "player1": {"id": "11", "name": "A"},
            "player2": {"id": "12", "name": "B"},
            "surface": "hard",
        }
        payload["upcoming"] = [fixture]
        payload["top_daily_picks"] = [fixture]
        payload["prime_picks"] = [fixture]
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return target


def test_private_serving_readback_is_exact_and_has_no_player_information(tmp_path):
    feed = candidate(tmp_path)
    result = serving_feed_readback(feed, now=NOW)
    assert result["schema"] == 1
    assert result["ok"] is True and result["stale"] is False
    assert result["ready"] is True
    assert result["betting_day"] == "2026-11-06"
    assert result["feed_sha256"] == hashlib.sha256(feed.read_bytes()).hexdigest()
    assert set(result["source_counts"]) == set(SERVING_COUNT_KEYS)
    assert result["source_counts"]["upcoming"] == 1
    assert result["visible_counts"]["top_daily_picks"] == 1
    assert result["visible_counts"]["prime_picks"] == 1
    assert not any(key in result for key in ("player1", "player2", "account", "ledger", "odds", "predictions"))
    assert verify_readback(feed, result, now=NOW)["status"] == "verified"


@pytest.mark.parametrize("key,mutation", [
    ("feed_sha256", "0" * 64),
    ("ready", False),
    ("stale", True),
    ("betting_day", "2026-11-05"),
    ("generated_at", "2026-11-05T06:10:00+00:00"),
    ("source_counts", {"upcoming": 0}),
    ("visible_counts", {"upcoming": 0}),
])
def test_deploy_readback_rejects_mismatch_and_does_not_confirm(key, mutation, tmp_path):
    feed = candidate(tmp_path)
    actual = serving_feed_readback(feed, now=NOW)
    actual[key] = mutation
    with pytest.raises(RuntimeError, match="mismatch"):
        verify_readback(feed, actual, now=NOW)


def test_deploy_readback_rejects_invalid_clock_and_invalid_schema(tmp_path):
    feed = candidate(tmp_path)
    actual = serving_feed_readback(feed, now=NOW)
    old = deepcopy(actual)
    old["observed_at_utc"] = (NOW - timedelta(minutes=5)).isoformat()
    with pytest.raises(RuntimeError, match="clock differs"):
        verify_readback(feed, old, now=NOW)
    actual["schema"] = 2
    with pytest.raises(ValueError, match="schema"):
        verify_readback(feed, actual, now=NOW)


def test_quiet_healthy_day_can_have_zero_picks_without_false_failure(tmp_path):
    feed = candidate(tmp_path, with_picks=False)
    actual = serving_feed_readback(feed, now=NOW)
    assert actual["ok"] is True
    assert all(n == 0 for n in actual["visible_counts"].values())
    assert verify_readback(feed, actual, now=NOW)["status"] == "verified"


def test_stale_unready_and_absent_serving_feed_fail_closed(tmp_path):
    old = candidate(tmp_path, generated="2026-11-05T06:10:00+00:00")
    old_status = serving_feed_readback(old, now=NOW)
    assert old_status["stale"] is True
    assert old_status["ok"] is False
    with pytest.raises(RuntimeError, match="not a current ready"):
        verify_readback(old, old_status, now=NOW)
    unready = candidate(tmp_path, ready=False)
    assert serving_feed_readback(unready, now=NOW)["ok"] is False
    with pytest.raises(ValueError, match="missing"):
        serving_feed_readback(tmp_path / "never-built.json", now=NOW)


def test_signed_internal_route_does_not_accept_anonymous_calls(monkeypatch, tmp_path):
    import function_app

    feed = candidate(tmp_path)
    monkeypatch.setattr(function_app, "FEED", feed)
    monkeypatch.setattr(function_app, "_live_worker_token_ok", lambda _req: False)
    forbidden = function_app.internal_serving_feed_readback(None)
    assert forbidden.status_code == 403
    assert "feed_sha256" not in forbidden.get_body().decode()

    monkeypatch.setattr(function_app, "_live_worker_token_ok", lambda _req: True)
    monkeypatch.setattr(function_app, "serving_feed_readback",
                        lambda p: serving_feed_readback(p, now=NOW))
    allowed = function_app.internal_serving_feed_readback(None)
    assert allowed.status_code == 200
    data = json.loads(allowed.get_body())
    assert data["feed_sha256"] == hashlib.sha256(feed.read_bytes()).hexdigest()
    assert "player1" not in str(data) and "player2" not in str(data)
    candidate(tmp_path, generated="2026-11-05T06:10:00+00:00")
    assert function_app.internal_serving_feed_readback(None).status_code == 503



def test_preflight_validates_candidate_without_token_or_http(monkeypatch, capsys, tmp_path):
    import scripts.verify_deployed_serving_feed as verifier

    monkeypatch.delenv("BLINQ_LIVE_WORKER_TOKEN", raising=False)
    monkeypatch.setattr(verifier, "serving_feed_readback",
                        lambda path: serving_feed_readback(path, now=NOW))
    monkeypatch.setattr(verifier, "read_protected",
                        lambda *_: (_ for _ in ()).throw(AssertionError("No HTTP during preflight")))
    good = candidate(tmp_path)
    verifier.main(["--feed", str(good), "--preflight-only"])
    assert "BLINQ_SERVING_PREFLIGHT" in capsys.readouterr().out
    bad = candidate(tmp_path, generated="2026-11-05T06:10:00+00:00")
    with pytest.raises(RuntimeError, match="Refusing deployment"):
        verifier.main(["--feed", str(bad), "--preflight-only"])


def test_two_production_paths_require_canary_before_issuance():
    for path, confirm in [
        (".github/workflows/ci.yml", "Confirm deployed prediction publication"),
        (".github/workflows/data.yml", "Confirm exactly deployed prediction publication"),
    ]:
        yml = (ROOT / path).read_text(encoding="utf-8")
        assert "Verify signed" in yml
        check = yml.index("python scripts/verify_deployed_serving_feed.py")
        deploy = yml.index("Deploy BlinQ to Azure Static Web Apps" if path.endswith("ci.yml") else "Deploy refreshed feed and application")
        issued = yml.index(confirm)
        assert deploy < check < issued
        preflight = yml.index("python scripts/verify_deployed_serving_feed.py --preflight-only")
        assert preflight < deploy
        assert "BLINQ_LIVE_WORKER_TOKEN:" in yml
        assert "--feed api/data/feed.json" in yml[check:issued]
    app = (ROOT / "api/function_app.py").read_text(encoding="utf-8")
    assert '@app.route(route="v1/internal/serving-feed-readback", methods=["GET"])' in app
    assert "if not _live_worker_token_ok(req):" in app[app.index("def internal_serving_feed_readback"):app.index('@app.route(route="v1/comparator/players"')]

