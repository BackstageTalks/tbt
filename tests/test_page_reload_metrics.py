"""Regression tests for page-reload telemetry separate from login accounting."""
from datetime import datetime, timezone
from unittest.mock import Mock
from tbt.services import page_reload_metrics as metrics

def test_reload_idempotent_and_non_login_storage(monkeypatch):
    saved = set()
    def create_entity(entity):
        key = (entity["PartitionKey"], entity["RowKey"])
        if key in saved:
            error = RuntimeError("duplicate")
            error.status_code = 409
            raise error
        saved.add(key)
    table = Mock()
    table.create_entity.side_effect = create_entity
    monkeypatch.setattr(metrics, "_table", lambda name: table if name == "BlinQPageReloadMetrics" else None)
    event = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert metrics.record_reload("user-1", event)
    assert not metrics.record_reload("user-1", event)
    assert not metrics.record_reload("user-1", "invalid")
    assert len(saved) == 1

def test_reload_rollups_local_day_and_account_isolation(monkeypatch):
    table = Mock()
    table.query_entities.side_effect = lambda query_filter: (
        [{"reloaded_at": "2026-10-08T05:00:00+00:00"},
         {"reloaded_at": "2026-10-07T20:00:00+00:00"},
         {"reloaded_at": "2026-09-29T12:00:00+00:00"}]
        if metrics._partition("user-1") in query_filter else [])
    monkeypatch.setattr(metrics, "_table", lambda name: table)
    result = metrics.load_reload_statistics(
        ["user-1", "user-2"], now=datetime(2026, 10, 8, 8, tzinfo=timezone.utc))
    assert result["user-1"] == {
        "reload_count_today": 1, "reload_count_7d": 2, "reload_count_30d": 3}
    assert result["user-2"] == {
        "reload_count_today": 0, "reload_count_7d": 0, "reload_count_30d": 0}
