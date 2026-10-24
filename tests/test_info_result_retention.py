"""Retention and irreversible all-delete boundaries for independently stored INFO results."""
from datetime import datetime, timedelta, timezone

import pytest

from tbt.services import admin_storage as storage


class MemoryTable:
    def __init__(self):
        self.rows = {}

    def get_entity(self, *, partition_key, row_key):
        return dict(self.rows[(partition_key, row_key)])

    def upsert_entity(self, entity, mode=None):
        key = (entity["PartitionKey"], entity["RowKey"])
        previous = self.rows.get(key, {}) if mode == "merge" else {}
        self.rows[key] = {**previous, **dict(entity)}

    def query_entities(self, query_filter=None):
        if query_filter and "PartitionKey eq '" in query_filter:
            partition = query_filter.split("PartitionKey eq '", 1)[1].split("'", 1)[0]
            return [dict(v) for (pk, _), v in self.rows.items() if pk == partition]
        return [dict(v) for v in self.rows.values()]

    def delete_entity(self, *, partition_key, row_key):
        del self.rows[(partition_key, row_key)]


@pytest.fixture
def tables(monkeypatch):
    mapping = {}
    monkeypatch.setattr(storage, "_table", lambda name: mapping.setdefault(name, MemoryTable()))
    return mapping


def add_row(client, key, settled_at, partition="info-results"):
    client.upsert_entity({
        "PartitionKey": partition, "RowKey": key,
        "source_id": "source", "settled_at": settled_at,
    })


def test_retention_keeps_recent_and_unknown_age_without_touching_original_messages(tables):
    now = datetime.now(timezone.utc)
    client = tables.setdefault(storage.INSIGHTS_TABLE, MemoryTable())
    add_row(client, "old", (now - timedelta(days=10)).isoformat())
    add_row(client, "new", (now - timedelta(days=2)).isoformat())
    add_row(client, "unknown", "malformed-timestamp")
    add_row(client, "original-info", (now - timedelta(days=400)).isoformat(), "insights")
    assert storage.info_result_retention_days() == 0
    assert storage.cleanup_info_results()["deleted"] == 0
    assert storage.save_info_result_retention(7, actor_id="admin") == 7
    result = storage.cleanup_info_results(actor_id="worker")
    assert result["deleted"] == 1 and result["failed"] == 0
    assert ("info-results", "old") not in client.rows
    assert ("info-results", "new") in client.rows
    assert ("info-results", "unknown") in client.rows
    assert ("insights", "original-info") in client.rows


def test_delete_all_ignores_retention_but_never_erases_non_result_partitions(tables):
    client = tables.setdefault(storage.INSIGHTS_TABLE, MemoryTable())
    now = datetime.now(timezone.utc).isoformat()
    add_row(client, "result-1", now)
    add_row(client, "result-2", now)
    add_row(client, "original-message", now, "insights")
    result = storage.cleanup_info_results(delete_all=True, actor_id="admin")
    assert result["deleted"] == 2 and result["failed"] == 0
    assert ("insights", "original-message") in client.rows


@pytest.mark.parametrize("days", [-1, 1, 31, 366, "30", None, True])
def test_retention_rejects_unsupported_values(tables, days):
    with pytest.raises(ValueError):
        storage.save_info_result_retention(days, actor_id="admin")


def test_admin_ui_requires_explicit_delete_confirmation():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    app = (root / "web" / "app.js").read_text(encoding="utf-8")
    api = (root / "api" / "function_app.py").read_text(encoding="utf-8")
    assert "admin-info-results-collapsible" in app
    assert "data-admin-action=\"info-results-delete-all\"" in app
    assert "DELETE ALL" in app
    assert "DELETE ALL INFO RESULTS" in api
