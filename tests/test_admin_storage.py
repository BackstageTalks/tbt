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


def test_legacy_info_runtime_is_healed_once_and_future_admin_choices_survive():
    payload = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    payload.pop("info_contract_revision", None)
    payload["notifications"].update({
        "enabled": False,
        "show_bell": False,
        "one_way": False,
        "mode": "legacy",
        "allow_user_replies": True,
        "read_tracking": False,
        "editable_levels": ["elite", "legend", "goat"],
        "info_min_level": "elite",
        "info_default_levels": ["elite", "legend", "goat"],
    })

    healed = admin_storage._normalize_membership_invariants(payload)
    notifications = healed["notifications"]
    assert healed["info_contract_revision"] == 1
    assert notifications["enabled"] is True
    assert notifications["show_bell"] is True
    assert notifications["mode"] == "one_way"
    assert notifications["one_way"] is True
    assert notifications["allow_user_replies"] is False
    assert notifications["read_tracking"] is True
    assert notifications["editable_levels"] == ["rookie", "pro", "elite", "legend", "goat"]
    assert notifications["info_min_level"] == "rookie"
    assert notifications["info_default_levels"] == ["rookie", "pro", "elite", "legend", "goat"]

    # The migration is one-shot. Once deployed, later Admin audience defaults
    # must remain user-managed instead of being reset on every read.
    notifications["info_min_level"] = "pro"
    notifications["info_default_levels"] = ["pro", "elite", "legend", "goat"]
    healed_again = admin_storage._normalize_membership_invariants(healed)
    assert healed_again["notifications"]["info_min_level"] == "pro"
    assert healed_again["notifications"]["info_default_levels"] == ["pro", "elite", "legend", "goat"]


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


def test_match_status_pending_roundtrip_and_compressed_large_snapshot(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    first = {
        "statuses": {},
        "pending": {"101": {"t": "2026-09-25T21:00:00+00:00",
                            "s": "11", "a": "11", "b": "22",
                            "c": "2026-09-25T23:00:00+00:00", "n": "2"}},
        "daily_attempts": 1,
        "daily_matches": 0,
        "daily_errors": {"ProviderError_HTTP_403": 1},
        "recent_candidates": 1,
        "today_candidates": 1,
    }
    saved = admin_storage.save_match_status_snapshot(first)
    assert saved["pending_count"] == 1
    assert saved["pending"]["101"]["n"] == "2"
    assert saved["daily_attempts"] == 1
    assert saved["daily_matches"] == 0
    assert saved["daily_errors"] == {"ProviderError_HTTP_403": 1}
    restored_first = admin_storage.load_match_status_snapshot()
    assert restored_first["pending"]["101"]["s"] == "11"
    assert restored_first["pending"]["101"]["n"] == "2"
    assert restored_first["daily_attempts"] == 1
    assert restored_first["daily_errors"] == {"ProviderError_HTTP_403": 1}
    huge = dict(first)
    huge["statuses"] = {
        str(i): {"status": "win", "checked_at": "2026-09-25T23:00:00+00:00",
                 "winner_id": "123", "provider_status": "finished ended " +
                 str(i).zfill(110)}
        for i in range(260)
    }
    huge["statuses"]["void_event"] = {
        "status": "void", "checked_at": "2026-09-25T23:00:00+00:00",
    }
    huge["pending"] = {
        str(i): {"t": "2026-09-25T21:00:00+00:00",
                 "s": "11", "a": "11", "b": "22",
                 "c": "2026-09-25T23:00:00+00:00"}
        for i in range(170)
    }
    admin_storage.save_match_status_snapshot(huge)
    assert table.single["payload"].startswith("gzip:")
    assert len(table.single["payload"].encode("utf-16-le")) < 60_000
    restored = admin_storage.load_match_status_snapshot()
    assert restored["statuses"]["100"]["status"] == "win"
    assert restored["statuses"]["259"]["status"] == "win"
    assert restored["statuses"]["void_event"]["status"] == "void"
    assert restored["pending"]["169"]["s"] == "11"
    assert restored["pending_count"] == 170


def test_runtime_ui_backup_preserves_previous_complete_published_version(monkeypatch):
    import copy
    table = FakeTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    original = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    first = copy.deepcopy(original)
    first["elements"]["HERO_BANNER_1"]["content"]["headline"] = "Original live headline"
    first["elements"]["HERO_BANNER_2"]["content"].update({
        "enabled": True, "image_url": "/api/v1/media/older-banner.webp",
        "link": "https://example.com/older-campaign",
    })
    admin_storage.save_runtime_ui_config(first, actor_id="original-editor")
    assert admin_storage.list_runtime_ui_snapshots() == []
    changed = copy.deepcopy(first)
    changed["elements"]["HERO_BANNER_1"]["content"]["headline"] = "Newer headline"
    result = admin_storage.save_runtime_ui_config(changed, actor_id="new-editor")
    assert result["saved"] is True and result["previous_snapshot_id"]
    snapshots = admin_storage.list_runtime_ui_snapshots()
    assert len(snapshots) == 1
    assert snapshots[0]["id"] == result["previous_snapshot_id"]
    assert snapshots[0]["previous_updated_by"] == "original-editor"
    # Azure stored the previous full compressed JSON, including unpublished
    # banners and their media paths and campaign links.
    previous_row = table.entities[0]
    assert previous_row["PartitionKey"] == "ui-config-history"
    previous = admin_storage._decode_runtime_ui_payload(previous_row["payload"])
    assert previous == first
    assert admin_storage.load_runtime_ui_config() == changed
    # Both the version listing and the exact full version must be recoverable.
    active_get = table.get_entity
    def indexed_get(*, partition_key, row_key):
        if partition_key == "ui-config-history":
            return next(row for row in table.entities if row["RowKey"] == row_key)
        return active_get(partition_key, row_key)
    monkeypatch.setattr(table, "get_entity", indexed_get)
    assert admin_storage.load_runtime_ui_snapshot(result["previous_snapshot_id"]) == first


def test_runtime_ui_backup_failure_does_not_overwrite_published_version(monkeypatch):
    import copy
    table = FakeTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    original = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    admin_storage.save_runtime_ui_config(copy.deepcopy(original))
    earlier_payload = table.single["payload"]
    def fail_create(_row):
        raise RuntimeError("Azure snapshot write failed")
    monkeypatch.setattr(table, "create_entity", fail_create)
    changed = copy.deepcopy(original)
    changed["hero_banner"]["slot_count"] = 2
    try:
        admin_storage.save_runtime_ui_config(changed)
    except admin_storage.AdminStorageUnavailable:
        pass
    else:
        raise AssertionError("Snapshot failure must block publishing")
    assert table.single["payload"] == earlier_payload


def test_ui_snapshot_id_validation_is_fail_closed():
    for invalid in ("../ui-config", "ui-config", "", "before-20260928T010101000000Z-bad!"):
        try:
            admin_storage.load_runtime_ui_snapshot(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("An untrusted snapshot key must be rejected")


def test_info_result_history_is_independent_and_can_be_corrected(monkeypatch):
    class MultiTable:
        def __init__(self):
            self.rows = {}
        def get_entity(self, partition_key, row_key):
            key=(partition_key,row_key)
            if key not in self.rows:
                raise KeyError(row_key)
            return dict(self.rows[key])
        def upsert_entity(self, entity, mode=None):
            self.rows[(entity["PartitionKey"],entity["RowKey"])] = dict(entity)
        def query_entities(self, query_filter=None):
            rows=list(self.rows.values())
            marker="PartitionKey eq '"
            if query_filter and marker in query_filter:
                key=query_filter.split(marker,1)[1].split("'",1)[0]
                rows=[row for row in rows if row.get("PartitionKey")==key]
            return [dict(row) for row in rows]
        def delete_entity(self, partition_key, row_key):
            key=(partition_key,row_key)
            if key not in self.rows:
                raise KeyError(row_key)
            del self.rows[key]

    table=MultiTable()
    table.rows[("insights","msg-info-1")]={
        "PartitionKey":"insights","RowKey":"msg-info-1",
        "title":"POR vyhrá aspoň jeden polčas","body":"POR -1.50",
        "type":"vip","priority":"normal","levels_json":'["rookie"]',
        "match_id":"event-1","active":True,"pinned":False,
        "active_from":"","active_until":"",
        "created_at":"2026-10-01T18:00:00+00:00","updated_at":"2026-10-01T18:00:00+00:00",
        "created_by":"admin","read_count":0,
    }
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)

    first=admin_storage.save_info_result("msg-info-1","win",actor_id="admin")
    assert first["outcome"]=="win"
    assert first["source_id"]=="msg-info-1"
    assert len(admin_storage.list_info_results())==1

    corrected=admin_storage.save_info_result("msg-info-1","loss",actor_id="admin")
    assert corrected["id"]==first["id"]
    assert admin_storage.list_info_results()[0]["outcome"]=="loss"

    table.delete_entity("insights","msg-info-1")
    history=admin_storage.list_info_results()
    assert len(history)==1
    assert history[0]["title"]=="POR vyhrá aspoň jeden polčas"

    removed=admin_storage.delete_info_result(first["id"],actor_id="admin")
    assert removed["deleted"] is True
    assert admin_storage.list_info_results()==[]
