"""Azure Table regression: automatic LIVE insights must persist scalar properties only."""

import json

import pytest

from tbt.services import admin_storage
from tbt.services import push_notifications


class StrictAzureInsightsTable:
    """Reject unsupported Azure Table arrays/maps before they enter production."""

    def __init__(self):
        self.rows = {}

    @staticmethod
    def validate(entity):
        unsupported = {
            key: type(value).__name__
            for key, value in entity.items()
            if isinstance(value, (list, dict, tuple, set))
        }
        assert not unsupported, f"Azure Table unsupported property types: {unsupported}"

    def get_entity(self, *, partition_key, row_key):
        key = (partition_key, row_key)
        if key not in self.rows:
            raise KeyError(row_key)
        return dict(self.rows[key])

    def create_entity(self, entity):
        self.validate(entity)
        key = (entity["PartitionKey"], entity["RowKey"])
        assert key not in self.rows
        self.rows[key] = dict(entity)

    def upsert_entity(self, entity, mode=None):
        self.validate(entity)
        key = (entity["PartitionKey"], entity["RowKey"])
        assert key in self.rows
        self.rows[key] = dict(entity)


@pytest.mark.parametrize(
    "kind,insight_id",
    [
        ("alert", "live-comeback-1234"),
        ("live_watch", "live-watch-1234"),
        ("set2", "live-set2-1234"),
    ],
)
@pytest.mark.parametrize("media_ids", [[], ["insight-AbCdE12345"]])
def test_automated_live_insights_create_and_refresh_azure_safe_properties(
    monkeypatch, kind, insight_id, media_ids
):
    table = StrictAzureInsightsTable()
    pushes = []
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    monkeypatch.setattr(admin_storage, "_live_deleted", lambda *args: False)
    monkeypatch.setattr(admin_storage, "live_alert_levels", lambda config=None: ["elite", "legend", "goat"])
    monkeypatch.setattr(push_notifications, "dispatch_insight_push", lambda item: pushes.append(item["id"]))

    payload = {
        "title": "LIVE signal",
        "body": "Verified LIVE evidence.",
        "type": kind,
        "priority": "important",
        "levels": ["elite"],
        "match_id": "1234",
        "media_ids": media_ids,
        "active": True,
    }
    first, created = admin_storage.save_automated_insight(
        payload, actor_id="live-radar", insight_id=insight_id
    )
    assert created is True
    assert first["id"] == insight_id
    assert first["media_ids"] == media_ids
    row = table.get_entity(partition_key="insights", row_key=insight_id)
    assert "media_ids" not in row
    assert json.loads(row["media_ids_json"]) == media_ids
    assert pushes == [insight_id]

    payload["body"] = "New LIVE snapshot; same issued message."
    second, created_again = admin_storage.save_automated_insight(
        payload, actor_id="live-radar", insight_id=insight_id
    )
    assert created_again is False
    assert second["body"] == payload["body"]
    assert second["media_ids"] == media_ids
    refreshed = table.get_entity(partition_key="insights", row_key=insight_id)
    assert "media_ids" not in refreshed
    assert json.loads(refreshed["media_ids_json"]) == media_ids
    assert pushes == [insight_id]
