from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_live_watch_is_valid_private_insight_type():
    from tbt.services import admin_storage
    assert "live_watch" in admin_storage._INSIGHT_TYPES


def test_info_can_target_lower_tiers_but_live_remains_elite_plus():
    from tbt.services.admin_storage import normalize_insight
    row = normalize_insight({"title": "x", "body": "y", "type": "vip", "levels": ["rookie", "pro"]})
    assert row["levels"] == ["rookie", "pro"]
    with pytest.raises(ValueError):
        normalize_insight({"title": "x", "body": "y", "type": "alert", "levels": ["rookie"]})


def test_ui_info_is_general_channel_while_live_remains_elite_plus():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    assert "const infoEligible=eligible" in app
    assert "const liveEligible=['elite','legend','goat','admin'].includes(plan)" in app
    assert "insight-audience-all" in app and "insight-audience-rookie" in app


def test_mega_data_does_not_auto_repair_history():
    script = (ROOT / "scripts/run_mega_data.py").read_text(encoding="utf-8")
    assert '"history-audit-before"' in script
    assert '_run("history-repair"' not in script


def test_historical_provider_self_match_is_quarantined(monkeypatch, match_factory):
    from tbt.providers.rapidapi import RapidTennisClient
    client = RapidTennisClient.__new__(RapidTennisClient)
    client.historical_event_quarantine = []
    client.calendar_categories = lambda day: [{"id": 3, "name": "ATP"}]
    client._category_id = lambda category: 3
    client._category_tour = lambda category: "atp"
    client.category_events = lambda category_id, day: [
        {"id": 777, "homeTeam": {"id": "A", "name": "A"}, "awayTeam": {"id": "A", "name": "A"}},
    ]
    client._is_singles_event = lambda raw: True
    client._event_tour = lambda raw, category_id, category_name: "atp"
    client.normalize_match = lambda raw, tour, historical: (_ for _ in ()).throw(
        ValueError("Invalid player identity: both sides have the same player ID")
    )
    base = match_factory("valid", "A", "B", "A")
    rows = client.matches_for_day("atp", base.scheduled_at.date(), historical=True)
    assert rows == []
    assert client.historical_event_quarantine[0]["reason"] == "provider_self_match_identity"
    assert client.historical_event_quarantine[0]["provider_event_id"] == "777"
