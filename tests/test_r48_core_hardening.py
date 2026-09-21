from datetime import datetime, timedelta, timezone

from tbt.services import admin_storage, live_comeback
from tbt.services.doubles_selection import walk_forward_validation


def test_live_publications_get_short_ttl_and_refresh_same_ids(monkeypatch):
    calls = []

    def fake_save(payload, *, actor_id="automation", insight_id):
        calls.append((insight_id, dict(payload)))
        return {"id": insight_id, **payload}, len([x for x in calls if x[0] == insight_id]) == 1

    monkeypatch.setattr(live_comeback, "save_automated_insight", fake_save)
    monkeypatch.setattr(live_comeback, "live_alert_levels", lambda: ["elite", "legend", "goat"])
    scanned = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
    candidate = {
        "event_id": "evt-1", "favorite": "Pair A", "opponent": "Pair B",
        "probability": 0.74, "odds": 1.42, "first_set": "4:6", "second_set": "2:1",
        "second_set_probability": 0.68, "second_set_odds": 1.75,
        "second_set_edge": 0.08, "second_set_ev": 0.19,
        "second_set_samples": 24, "second_set_quality": "high",
    }
    scan = {"scanned_at": scanned.isoformat(), "candidates": [candidate], "signals": []}
    first = live_comeback.publish_radar_signals(scan)
    second = live_comeback.publish_radar_signals(scan)
    assert first["created"] == 2
    assert second["created"] == 0
    ids = [row[0] for row in calls]
    assert ids.count("live-set2-evt-1") == 2
    assert ids.count("live-watch-evt-1") == 2
    for _, payload in calls:
        assert payload["active_until"]
        expiry = datetime.fromisoformat(payload["active_until"])
        assert scanned < expiry <= scanned + timedelta(minutes=30)


def test_automated_insight_refreshes_existing_without_recreate(monkeypatch):
    class FakeTable:
        def __init__(self):
            self.row = None
            self.created = 0
            self.updated = 0
        def get_entity(self, **_kwargs):
            if self.row is None:
                raise KeyError("missing")
            return dict(self.row)
        def create_entity(self, entity):
            self.created += 1
            self.row = dict(entity)
        def upsert_entity(self, entity, mode=None):
            self.updated += 1
            self.row = dict(entity)

    table = FakeTable()
    monkeypatch.setattr(admin_storage, "_table", lambda _name: table)
    monkeypatch.setattr(admin_storage, "info_alert_levels", lambda *_a, **_k: ["rookie", "pro", "elite", "legend", "goat"])

    base = {
        "title": "Initial", "body": "one", "type": "info", "priority": "normal",
        "levels": ["rookie"], "active": True,
        "active_until": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    }
    _, created1 = admin_storage.save_automated_insight(base, insight_id="auto-test-1")
    updated_payload = dict(base, title="Refreshed", body="two", active_until=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat())
    item2, created2 = admin_storage.save_automated_insight(updated_payload, insight_id="auto-test-1")
    assert created1 is True
    assert created2 is False
    assert table.created == 1
    assert table.updated == 1
    assert item2["title"] == "Refreshed"
    assert item2["body"] == "two"


def _doubles_row(i: int) -> dict:
    when = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i * 3)
    return {
        "event_id": f"e{i}", "scheduled_at": when.isoformat(), "surface": "Hard",
        "player1_id": "team-a", "player1_name": "A1 / A2",
        "player1_members": [{"id": "a1", "name": "A1"}, {"id": "a2", "name": "A2"}],
        "player2_id": "team-b", "player2_name": "B1 / B2",
        "player2_members": [{"id": "b1", "name": "B1"}, {"id": "b2", "name": "B2"}],
        "winner_id": "team-a" if i % 3 else "team-b", "status": "finished",
    }


def test_doubles_has_strict_walk_forward_validation_but_does_not_claim_edge():
    report = walk_forward_validation([_doubles_row(i) for i in range(460)])
    assert report["method"] == "strict_walk_forward_pre_match_ratings"
    assert report["samples"] >= 200
    assert report["validation_ready"] is True
    assert 0 <= report["accuracy"] <= 1
    assert report["brier"] is not None
    assert report["betting_edge_proven"] is False
    assert "bookmaker" in report["betting_edge_note"].lower()
