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


def test_runtime_ui_config_is_compressed_for_azure_table_property(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    payload = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    payload["telegram_groups"] = json.loads((ROOT / "web" / "config" / "telegram-groups.json").read_text(encoding="utf-8"))
    admin_storage.save_runtime_ui_config(payload, actor_id="admin")
    stored = table.single["payload"]
    assert stored.startswith("gzip:")
    # Keep well below Azure Table's single-property ceiling.
    assert len(stored.encode("utf-8")) < 60_000
    assert admin_storage.load_runtime_ui_config() == payload


def test_runtime_ui_config_reads_legacy_plain_json(monkeypatch):
    table = FakeTable()
    payload = {"schema": 1, "legacy": True}
    table.single = {"PartitionKey": "runtime", "RowKey": "ui-config", "payload": json.dumps(payload)}
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    assert admin_storage.load_runtime_ui_config() == payload


def test_banner_analytics_are_aggregated_by_campaign_and_unique_visitor(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)

    admin_storage.record_banner_event({
        "event_type": "impression", "slot_id": "HERO_BANNER_1",
        "campaign_id": "campaign-1", "advertiser_id": "partner-a", "client_id": "browser-a",
    })
    admin_storage.record_banner_event({
        "event_type": "impression", "slot_id": "HERO_BANNER_1",
        "campaign_id": "campaign-1", "advertiser_id": "partner-a", "client_id": "browser-a",
    })
    admin_storage.record_banner_event({
        "event_type": "click", "slot_id": "HERO_BANNER_1",
        "campaign_id": "campaign-1", "advertiser_id": "partner-a", "client_id": "browser-a",
    })
    admin_storage.record_banner_event({
        "event_type": "impression", "slot_id": "HERO_BANNER_2",
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
    assert row["slots"]["HERO_BANNER_1"] == 3
    assert row["slots"]["HERO_BANNER_2"] == 1


def test_banner_event_rejects_bad_ids(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    try:
        admin_storage.record_banner_event({"event_type": "click", "slot_id": "bad id with spaces"})
    except ValueError as exc:
        assert "identifier" in str(exc)
    else:
        raise AssertionError("Expected invalid analytics identifier")


def test_runtime_ui_config_accepts_current_hero_creative_variants():
    payload = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    hero = payload["hero_banner"]
    hero["enabled"] = True
    hero["slot_count"] = 2
    hero["rotation_seconds"] = 6

    elements = payload["elements"]
    elements["HERO_BANNER_1"]["content"]["image_url"] = "/assets/hero-reference-exact-v680.webp"
    elements["HERO_BANNER_1"]["content"]["mobile_image_url"] = "/assets/tennis-hero-v6524.webp"
    elements["HERO_BANNER_1"]["content"]["headline"] = "Tennis insights for a smarter tomorrow."

    assert admin_storage.validate_ui_config(payload) is payload


def test_live_worker_status_tracks_last_success_separately_from_failed_attempt(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)

    first = admin_storage.save_live_worker_status({
        "scanned_at": "2026-09-20T11:42:00+00:00",
        "live_events": 4,
    })
    assert first["last_success_at"] == "2026-09-20T11:42:00+00:00"
    assert first["last_error"] == ""

    failed = admin_storage.save_live_worker_status({
        "scanned_at": "2026-09-20T11:47:00+00:00",
        "last_success_at": first["last_success_at"],
        "last_error": "ProviderError",
    })
    assert failed["scanned_at"] == "2026-09-20T11:47:00+00:00"
    assert failed["last_success_at"] == "2026-09-20T11:42:00+00:00"
    assert failed["last_error"] == "ProviderError"
