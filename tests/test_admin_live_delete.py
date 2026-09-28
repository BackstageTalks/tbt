"""LIVE admin deletion: entries and settled results are independently removable.

All tests use in-memory Azure Table semantics; no real messages or sports API.
"""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from tbt.services import admin_storage


class MemoryTable:
    def __init__(self):
        self.rows = {}
        self.fail_tombstone = False

    def get_entity(self, partition_key, row_key):
        return deepcopy(self.rows[(partition_key, row_key)])

    def upsert_entity(self, entity, mode=None):
        if entity["PartitionKey"] == "live-deletions" and self.fail_tombstone:
            raise OSError("storage unavailable")
        self.rows[(entity["PartitionKey"], entity["RowKey"])] = deepcopy(entity)

    def create_entity(self, entity):
        key = (entity["PartitionKey"], entity["RowKey"])
        if key in self.rows:
            raise RuntimeError("already exists")
        self.rows[key] = deepcopy(entity)

    def delete_entity(self, partition_key, row_key):
        del self.rows[(partition_key, row_key)]

    def query_entities(self, query_filter=None):
        partition = query_filter.split("'", 2)[1] if query_filter else None
        return [deepcopy(row) for (pk, _), row in self.rows.items()
                if pk == partition or partition is None]


@pytest.fixture
def storage(monkeypatch):
    table = MemoryTable()
    monkeypatch.setattr(admin_storage, "_table", lambda _name: table)
    monkeypatch.setattr(admin_storage, "live_alert_levels",
                        lambda config=None: ["elite", "legend", "goat"])
    from tbt.services import push_notifications
    monkeypatch.setattr(push_notifications, "dispatch_insight_push", lambda _item: None)
    return table


def publish(record_id, kind, *, levels=None):
    return admin_storage.save_automated_insight({
        "title": "Autonomous LIVE " + record_id, "body": "One LIVE match update.",
        "type": kind, "levels": levels or ["elite"], "active": True,
    }, insight_id=record_id)


def result(record_id, kind, event="123", *, settled_at="2026-09-27T20:00:00+00:00"):
    return admin_storage.save_live_radar_result({
        "kind": kind, "outcome": "win" if kind == "comeback" else "loss",
        "event_id": event, "title": kind + " confirmed",
        "source_id": "live-comeback-" + event,
        "signal_at": "2026-09-27T19:00:00+00:00",
        "settled_at": settled_at,
    }, result_id=record_id)


def test_delete_one_live_post_not_its_separate_result(storage):
    post, created = publish("live-comeback-123", "alert")
    publish("live-watch-456", "live_watch")
    result("live-result-comeback-123", "comeback")
    assert created and post["id"] == "live-comeback-123"
    assert len(admin_storage.list_insights(plan="elite")["items"]) == 2

    removed = admin_storage.delete_insight("live-comeback-123", actor_id="admin-1")
    assert removed == {"deleted": True, "suppressed": True}
    assert admin_storage.load_insight_by_id("live-comeback-123") is None
    post, created = publish("live-comeback-123", "alert")
    assert created is False and post.get("suppressed")
    assert {x["id"] for x in admin_storage.list_insights(plan="elite")["items"]} == {
        "live-watch-456"
    }
    assert len(admin_storage.list_live_radar_results()) == 1
    tomb = storage.rows[("live-deletions", "insight:live-comeback-123")]
    assert tomb["deleted_by"] == "admin-1"


def test_delete_one_second_set_result_does_not_delete_comeback_or_set2_post(storage):
    publish("live-set2-123", "set2")
    result("live-result-set2-123", "set2")
    result("live-result-comeback-123", "comeback")
    out = admin_storage.delete_live_radar_result(
        "live-result-set2-123", actor_id="admin-2"
    )
    assert out == {"deleted": True, "id": "live-result-set2-123", "kind": "set2"}
    assert [row["kind"] for row in admin_storage.list_live_radar_results()] == [
        "comeback"
    ]
    assert admin_storage.load_insight_by_id("live-set2-123") is not None
    assert result("live-result-set2-123", "set2").get("suppressed") is True
    assert [row["kind"] for row in admin_storage.list_live_radar_results()] == [
        "comeback"
    ]
    assert storage.rows[("live-deletions", "result:live-result-set2-123")][
        "deleted_by"
    ] == "admin-2"


def test_delete_auto_set2_post_prevents_republication_but_retains_result(storage):
    publish("live-set2-123", "set2")
    result("live-result-set2-123", "set2")
    assert admin_storage.delete_insight("live-set2-123")["deleted"]
    assert publish("live-set2-123", "set2")[1] is False
    assert len(admin_storage.list_live_radar_results()) == 1
    assert admin_storage.delete_live_radar_result("live-result-set2-123")["deleted"]
    assert not admin_storage.list_live_radar_results()


def test_invalid_ids_unrelated_info_and_missing_records(storage):
    with pytest.raises(ValueError, match="Invalid LIVE result"):
        admin_storage.delete_live_radar_result("live-set2-123")
    with pytest.raises(ValueError, match="Invalid LIVE result"):
        admin_storage.delete_live_radar_result("live-result-invalid-123")
    with pytest.raises(ValueError, match="Invalid insight"):
        admin_storage.delete_insight("../bad")
    info = admin_storage.save_insight({
        "title": "INFO", "body": "Unrelated", "type": "vip",
        "levels": ["rookie"], "active": True,
    }, actor_id="admin")
    assert admin_storage.delete_insight(info["id"]) == {
        "deleted": True, "suppressed": False
    }
    assert not [k for k in storage.rows if k[0] == "live-deletions"]
    assert admin_storage.delete_live_radar_result(
        "live-result-set2-nonexistent"
    )["deleted"] is False


def test_failed_tombstone_write_never_deletes_live_row(storage):
    publish("live-watch-123", "live_watch")
    result("live-result-comeback-123", "comeback")
    storage.fail_tombstone = True
    with pytest.raises(admin_storage.AdminStorageUnavailable):
        admin_storage.delete_insight("live-watch-123")
    assert admin_storage.load_insight_by_id("live-watch-123") is not None
    with pytest.raises(admin_storage.AdminStorageUnavailable):
        admin_storage.delete_live_radar_result("live-result-comeback-123")
    assert len(admin_storage.list_live_radar_results()) == 1



def test_member_live_history_respects_kind_levels_and_time_windows(storage):
    now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
    result("live-result-comeback-recent", "comeback", "c1",
           settled_at="2026-09-28T11:00:00+00:00")
    result("live-result-comeback-old", "comeback", "c2",
           settled_at="2026-09-27T10:00:00+00:00")
    result("live-result-set2-recent", "set2", "s1",
           settled_at="2026-09-28T11:30:00+00:00")
    config = {"notifications": {
        "live_min_level": "elite",
        "live_history": {
            "comeback": {"levels": ["legend", "goat"], "hours": 24},
            "set2": {"levels": ["elite", "legend", "goat"], "hours": 72},
        },
    }}

    # Admin callers omit plan and always retain the complete durable history.
    assert len(admin_storage.list_live_radar_results(config=config, now=now)) == 3

    elite = admin_storage.list_live_radar_results(
        plan="elite", config=config, now=now
    )
    assert [(row["kind"], row["event_id"]) for row in elite] == [("set2", "s1")]

    legend = admin_storage.list_live_radar_results(
        plan="legend", config=config, now=now
    )
    assert {(row["kind"], row["event_id"]) for row in legend} == {
        ("comeback", "c1"), ("set2", "s1")
    }


def test_zero_hour_history_and_levels_below_live_minimum_never_leak(storage):
    now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
    result("live-result-comeback-123", "comeback", "c1",
           settled_at="2026-09-28T11:00:00+00:00")
    result("live-result-set2-123", "set2", "s1",
           settled_at="2026-09-28T11:00:00+00:00")
    config = {"notifications": {
        "live_min_level": "elite",
        "live_history": {
            # Rookie cannot widen a history audience below global LIVE access.
            "comeback": {"levels": ["rookie", "elite"], "hours": 24},
            "set2": {"levels": ["elite", "legend", "goat"], "hours": 0},
        },
    }}

    assert admin_storage.live_history_rule("comeback", config) == {
        "levels": ["elite"], "hours": 24
    }
    assert [row["kind"] for row in admin_storage.list_live_radar_results(
        plan="elite", config=config, now=now
    )] == ["comeback"]
    assert admin_storage.list_live_radar_results(
        plan="rookie", config=config, now=now
    ) == []
