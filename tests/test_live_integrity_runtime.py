"""LIVE integrity tests: no false-green cron and display-only settlement metadata."""
import json
from datetime import datetime, timezone

import function_app
from tbt.services import admin_storage
from tbt.services.match_status import runtime_settled_results
from tbt.services.results_archive import settled_archive_candidates


class MemoryTable:
    def __init__(self):
        self.rows = {}

    def upsert_entity(self, entity, mode=None):
        self.rows[(entity["PartitionKey"], entity["RowKey"])] = dict(entity)

    def get_entity(self, *, partition_key, row_key):
        return dict(self.rows[(partition_key, row_key)])

    def query_entities(self, query_filter=None):
        partition = query_filter.split("'")[1]
        return [dict(row) for (pk, _), row in self.rows.items() if pk == partition]

    def delete_entity(self, *, partition_key, row_key):
        self.rows.pop((partition_key, row_key), None)


class WorkerRequest:
    headers = {"X-Blinq-Worker-Token": "test-token"}


def body(response):
    return json.loads(response.get_body().decode("utf-8"))


def _stub_worker(monkeypatch, scan):
    monkeypatch.setenv("BLINQ_LIVE_WORKER_TOKEN", "test-token")
    monkeypatch.setattr(function_app, "_run_live_radar", lambda **kwargs: dict(scan))
    monkeypatch.setattr(function_app, "load_live_worker_status", lambda: {
        "scanned_at": "2026-10-08T18:00:00+00:00",
        "last_success_at": "2026-10-08T18:00:00+00:00",
    })


def _scan(**kwargs):
    return {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "live_events": 5, "prime_total": 25, "prime_eligible": 25,
        "candidates": [], "signals": [], "created": 0,
        **kwargs,
    }


def test_alert_storage_failure_is_http_503_not_false_green(monkeypatch):
    _stub_worker(monkeypatch, _scan(alert_storage_unavailable=True))
    written = []
    monkeypatch.setattr(function_app, "save_live_worker_status", lambda payload: written.append(dict(payload)))
    response = function_app.internal_live_radar_worker(WorkerRequest())
    result = body(response)
    assert response.status_code == 503
    assert result["error"] == "live_alert_storage_unavailable"
    assert result["heartbeat_persisted"] is True
    assert written[0]["last_error"] == "live_alert_storage_unavailable"
    assert written[0]["last_success_at"] == "2026-10-08T18:00:00+00:00"


def test_alert_publication_exception_is_http_503(monkeypatch):
    _stub_worker(monkeypatch, _scan(alert_publish_error="RuntimeError"))
    monkeypatch.setattr(function_app, "save_live_worker_status", lambda payload: payload)
    response = function_app.internal_live_radar_worker(WorkerRequest())
    assert response.status_code == 503
    assert body(response)["error"] == "live_alert_publish_failed"


def test_heartbeat_write_failure_is_http_503(monkeypatch):
    _stub_worker(monkeypatch, _scan())
    def broken(payload):
        raise admin_storage.AdminStorageUnavailable("synthetic outage")
    monkeypatch.setattr(function_app, "save_live_worker_status", broken)
    response = function_app.internal_live_radar_worker(WorkerRequest())
    assert response.status_code == 503
    assert body(response)["heartbeat_persisted"] is False


def test_live_heartbeat_preserves_prime_and_set2_stats(monkeypatch):
    table = MemoryTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)
    payload = function_app._public_live_radar_payload(_scan(
        set2_candidates=2, set2_priced=1, set2_eligible=1,
        set2_push_thresholds={"min_samples": 10},
        candidates=[{"event_id": "101", "second_set_odds": 1.7}],
    ))
    admin_storage.save_live_worker_status(payload)
    reloaded = admin_storage.load_live_worker_status()
    assert reloaded["prime_total"] == 25
    assert reloaded["prime_eligible"] == 25
    assert reloaded["set2_candidates"] == 2
    assert reloaded["set2_priced"] == 1
    assert reloaded["set2_eligible"] == 1
    assert reloaded["set2_push_thresholds"]["min_samples"] == 10
    assert reloaded["candidate_items"][0]["event_id"] == "101"


def test_settled_peak_and_first_set_survive_snapshot_and_archive(monkeypatch):
    table = MemoryTable()
    monkeypatch.setattr(admin_storage, "_table", lambda _: table)
    status = {
        "status": "win", "checked_at": "2026-10-08T14:00:00Z",
        "winner_id": "11", "provider_status": "finished ended",
        "first_set_outcome": "loss", "first_set_score": "4:6",
        "max_live_odds": 4.25, "max_live_odds_at": "2026-10-08T13:45:00Z",
        "live_odds_observations": 3,
    }
    admin_storage.save_match_status_snapshot({"statuses": {"101": status}})
    restored = admin_storage.load_match_status_snapshot()
    one = restored["statuses"]["101"]
    assert one["first_set_outcome"] == "loss"
    assert one["first_set_score"] == "4:6"
    assert one["max_live_odds"] == 4.25
    assert one["live_odds_scope"] == "comeback_after_first_set_loss"
    assert one["live_odds_observations"] == 3

    row = {
        "event_id": "101", "scheduled_at": "2026-10-08T12:00:00Z",
        "winner_id": "11", "player1": {"id": "11", "name": "Alpha"},
        "player2": {"id": "22", "name": "Beta"},
        "betting": {"odds": 1.75, "selection_id": "11"},
    }
    feed = {"generated_at": "2026-10-08T04:02:00Z",
            "top_daily_picks": [row], "results": []}
    archived = settled_archive_candidates(feed, restored["statuses"])
    assert len(archived) == 1
    pub = archived[0]["market_publications"][0]
    assert pub["odds"] == 1.75  # NEVER use the LIVE price for betting ROI
    assert pub["result"]["profit_units"] == 0.75
    assert pub["result"]["max_live_odds"] == 4.25
    assert pub["result"]["first_set_outcome"] == "loss"


def test_invalid_context_is_discarded_without_changing_settlement(monkeypatch):
    table = MemoryTable()
    monkeypatch.setattr(admin_storage, "_table", lambda _: table)
    row = {"status": "loss", "provider_status": "finished ended",
           "first_set_outcome": "whatever", "first_set_score": "10:10",
           "max_live_odds": 999999}
    admin_storage.save_match_status_snapshot({"statuses": {"101": row}})
    persisted = admin_storage.load_match_status_snapshot()["statuses"]["101"]
    assert persisted["status"] == "loss"
    for field in ("first_set_outcome", "first_set_score", "max_live_odds"):
        assert field not in persisted
