from datetime import datetime, timezone
import json
from pathlib import Path

from tbt.services import admin_storage

ROOT = Path(__file__).resolve().parents[1]


class FakeTable:
    def __init__(self):
        self.entities = []
        self.single = None

    def upsert_entity(self, entity, mode=None):
        self.single = dict(entity)

    def get_entity(self, partition_key, row_key):
        if not self.single:
            raise KeyError(row_key)
        return dict(self.single)

    def create_entity(self, entity):
        self.entities.append(dict(entity))

    def query_entities(self, query_filter=None):
        if not query_filter:
            return list(self.entities)
        marker="PartitionKey eq '"
        if marker in query_filter:
            key=query_filter.split(marker,1)[1].split("'",1)[0]
            return [row for row in self.entities if row.get('PartitionKey')==key]
        return list(self.entities)


def test_runtime_ui_config_round_trip(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    payload = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    saved = admin_storage.save_runtime_ui_config(payload, actor_id="admin")
    assert saved["saved"] is True
    assert admin_storage.load_runtime_ui_config() == payload
    assert table.single["updated_by"] == "admin"


def test_banner_analytics_are_aggregated_by_campaign_and_unique_visitor(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)

    admin_storage.record_banner_event({
        "event_type": "impression", "slot_id": "CONTENT_TOP_1",
        "campaign_id": "campaign-1", "advertiser_id": "partner-a", "client_id": "browser-a",
    })
    admin_storage.record_banner_event({
        "event_type": "impression", "slot_id": "CONTENT_TOP_1",
        "campaign_id": "campaign-1", "advertiser_id": "partner-a", "client_id": "browser-a",
    })
    admin_storage.record_banner_event({
        "event_type": "click", "slot_id": "CONTENT_TOP_1",
        "campaign_id": "campaign-1", "advertiser_id": "partner-a", "client_id": "browser-a",
    })
    admin_storage.record_banner_event({
        "event_type": "impression", "slot_id": "CONTENT_BOTTOM_2",
        "campaign_id": "campaign-1", "advertiser_id": "partner-a", "client_id": "browser-b",
    })

    summary = admin_storage.banner_analytics_summary(days=30)
    assert summary["available"] is True
    assert summary["summary"]["impressions"] == 3
    assert summary["summary"]["unique_impressions"] == 2
    assert summary["summary"]["clicks"] == 1
    assert summary["summary"]["unique_clicks"] == 1
    assert summary["summary"]["campaigns"] == 1
    row = summary["campaigns"][0]
    assert row["campaign_id"] == "campaign-1"
    assert row["impressions"] == 3
    assert row["unique_impressions"] == 2
    assert row["clicks"] == 1
    assert row["slots"]["CONTENT_TOP_1"] == 3
    assert row["slots"]["CONTENT_BOTTOM_2"] == 1


def test_banner_event_rejects_bad_ids(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    try:
        admin_storage.record_banner_event({"event_type": "click", "slot_id": "bad id with spaces"})
    except ValueError as exc:
        assert "identifier" in str(exc)
    else:
        raise AssertionError("Expected invalid analytics identifier")


def test_runtime_ui_config_accepts_fixed_campaign_creative_variants():
    payload = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    payload["advertisers"]["partner-a"] = {"name": "Partner A"}
    payload["campaigns"]["campaign-a"] = {
        "name": "Campaign A",
        "advertiser_id": "partner-a",
        "creative_mode": "full",
        "show_copy": False,
        "image_url": "/assets/fallback.webp",
        "images": {
            "1": "/assets/ad-small.webp",
            "2": "https://cdn.example/ad-wide.webp",
            "4": "/assets/ad-full.webp",
        },
    }
    assert admin_storage.validate_ui_config(payload) is payload
