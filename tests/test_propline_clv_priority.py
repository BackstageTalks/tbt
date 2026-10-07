import base64
import importlib
import os
import sys

import pytest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

os.environ.setdefault("PROPL", "test-secret")
os.environ.setdefault("TBT_DATA_GH_TOKEN", "test-token")

collector = importlib.import_module("propline_clv_collect")


def _event(event_id, start, home, away):
    return {
        "id": str(event_id),
        "commence_time": start,
        "home_team": home,
        "away_team": away,
        "tournament_name": "Test ATP",
        "tour": "ATP",
    }


def test_propline_picker_prioritizes_blinq_pair_before_nearer_control():
    now = datetime(2026, 9, 30, 10, tzinfo=timezone.utc)
    events = [
        _event(1, "2026-09-30T11:00:00Z", "Control A", "Control B"),
        _event(2, "2026-09-30T15:00:00Z", "Karolina Muchova", "Rebecca Sramkova"),
        _event(3, "2026-09-30T12:00:00Z", "Control C", "Control D"),
    ]
    pair = collector.player_pair("Karolína Muchová", "Rebecca Šramková")
    selected, eligible = collector.pick_events(events, now, {pair})
    assert eligible == 3
    assert selected[0][3] == "2"
    assert selected[0][0] == 0


def test_clv_routing_uses_hourly_propline_and_hourly_bounded_the_odds_consensus():
    status = (ROOT / ".github/workflows/match-status.yml").read_text(encoding="utf-8")
    data = (ROOT / ".github/workflows/data.yml").read_text(encoding="utf-8")
    odds = (ROOT / ".github/workflows/the-odds-clv.yml").read_text(encoding="utf-8")
    propline = (ROOT / ".github/workflows/propline-clv-pilot.yml").read_text(encoding="utf-8")

    assert "propline-clv-pilot.yml" in status
    assert "events_per_run=12" in status
    assert "the-odds-clv.yml" in status
    assert "reason=hourly" in status
    assert "propline-clv-pilot.yml" in data
    assert "the-odds-clv.yml" in data
    assert 'CLV_DAILY_CREDIT_CAP: "300"' in odds
    assert 'CLV_MAX_SPORTS_PER_RUN: "8"' in odds
    assert 'CLV_PROVIDER_RESERVE: "100"' in odds
    assert "  schedule:" not in odds
    assert "GH_TOKEN: ${{ secrets.TBT_DATA_GH_TOKEN }}" in propline
    assert "  push:" in propline
    assert '"scripts/propline_clv_collect.py"' in propline
    assert "if: needs.collect.result == 'success'" in propline


def test_propline_picker_orders_top_then_value_then_other_blinq_offer():
    now = datetime(2026, 9, 30, 10, tzinfo=timezone.utc)
    events = [
        _event(11, "2026-09-30T11:00:00Z", "Prime A", "Prime B"),
        _event(12, "2026-09-30T14:00:00Z", "Top A", "Top B"),
        _event(13, "2026-09-30T12:00:00Z", "Value A", "Value B"),
    ]
    priorities = {
        collector.player_pair("Top A", "Top B"): 0,
        collector.player_pair("Value A", "Value B"): 1,
        collector.player_pair("Prime A", "Prime B"): 2,
    }
    selected, eligible = collector.pick_events(events, now, priorities)
    assert eligible == 3
    assert [item[3] for item in selected] == ["12", "13", "11"]
    assert [item[0] for item in selected] == [0, 1, 2]



def test_clv_snapshot_preserves_local_gzip_and_verifies_ambiguous_put(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(collector, "api_calls", 7)
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    captured = {}

    def fake_github(path, method="GET", data=None, missing_ok=False):
        if method == "PUT":
            payload = base64.b64decode(data["content"])
            captured["payload"] = payload
            captured["path"] = path
            raise RuntimeError("HTTP 500 from GitHub")
        assert path == captured["path"]
        payload = captured["payload"]
        return {
            "sha": collector._git_blob_sha(payload),
            "size": len(payload),
        }

    monkeypatch.setattr(collector, "github", fake_github)
    remote, local, attempts = collector.save_snapshot(
        "research/propline_clv/2026-10-07",
        {"schema": 1, "events": [{"event_id": "1"}]},
    )
    assert remote.startswith("research/propline_clv/2026-10-07/")
    assert attempts == 1
    local_path = Path(local)
    assert local_path.is_file()
    assert local_path.read_bytes() == captured["payload"]


def test_clv_snapshot_keeps_artifact_when_permanent_write_stays_down(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(collector, "api_calls", 5)
    monkeypatch.setattr(collector.time, "sleep", lambda *_: None)

    def failed_github(path, method="GET", data=None, missing_ok=False):
        if method == "PUT":
            raise RuntimeError("HTTP 500 from GitHub")
        return None

    monkeypatch.setattr(collector, "github", failed_github)
    with pytest.raises(RuntimeError, match="local artifact preserved"):
        collector.save_snapshot(
            "research/propline_clv/2026-10-07",
            {"schema": 1, "events": []},
        )
    assert (tmp_path / "reports/propline_clv_snapshot.json.gz").is_file()


def test_clv_workflow_uploads_raw_snapshot_fallback():
    workflow = (ROOT / ".github/workflows/propline-clv-pilot.yml").read_text(
        encoding="utf-8"
    )
    assert "reports/propline_clv_snapshot.json.gz" in workflow
