import importlib
import os
import sys
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
