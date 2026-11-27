from datetime import datetime, timezone
import json

import httpx
import pytest

from tbt.errors import ProviderError
from tbt.providers import rapidapi
from tbt.services.hourly_collection import aggregate, build_run
from tbt.services.hourly_http_metrics import HourlyHttpMetrics


NOW = datetime(2026, 11, 27, tzinfo=timezone.utc)
ENDPOINT = "/api/tennis/event/{id}/statistics"


def test_attempts_cover_retry_empty_failure_and_budget(monkeypatch):
    monkeypatch.setattr(rapidapi.time, "sleep", lambda _: None)
    monkeypatch.setattr(rapidapi, "_enforce_provider_day_hard_stop", lambda: None)
    monkeypatch.setattr(rapidapi, "_require_provider_remaining_header", lambda: False)
    monkeypatch.delenv("BLINQ_API_AUTOFILL_STOP_AT_UTC", raising=False)
    client = object.__new__(rapidapi.RapidTennisClient)
    client._throttle = lambda: None
    client.request_count = 0
    client.http_metrics = HourlyHttpMetrics()
    client.request_limit = 8
    client.request_budget = None
    client.rate_limit_remaining = None
    client.retry_attempts = 2

    def respond(request):
        code, body = next(responses)
        if code is None:
            raise httpx.ConnectError("offline fixture", request=request)
        return httpx.Response(code, content=body)

    responses = iter([
        (503, b""), (200, b'{"statistics":[{"period":"ALL","groups":[{}]}]}'),
        (204, b""), (404, b""), (200, b'{"statistics":[]}'),
        (200, b"broken"), (None, b""), (429, b""),
    ])
    client.cfg = type("Config", (), {"rapidapi_key": "fixture", "rapidapi_host": "fixture.test", "rapidapi_base_url": "https://fixture.test"})()
    with httpx.Client(transport=httpx.MockTransport(respond)) as client.client:
        for _ in range(4):
            client._get("/api/tennis/event/123/statistics", optional_not_found=True)
        with pytest.raises(ProviderError):
            client._get("/api/tennis/event/123/statistics")
        with pytest.raises(rapidapi.RequestBudgetExceeded):
            client._get("/api/tennis/event/123/statistics")
    assert client.http_metrics.snapshot()["endpoints"] == {ENDPOINT: {
        "503_http": 1, "200_data": 1, "204_empty": 1, "404_http": 1,
        "200_empty": 1, "200_invalid_json": 1, "transport": 1, "429_http": 1,
    }}


def test_primary_and_fallback_readbacks_are_reconciled(tmp_path):
    def write(name, data):
        (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")

    write("hourly_primary_collection.json", {
        "attempts": 2, "endpoints": {ENDPOINT: {"200_data": 2}},
        "paid_statistic_values": 1, "conflicts": {"statistics": 1},
    })
    write("statistics_readback.json", {
        "status": "VERIFIED", "persisted_enriched_matches": 1,
        "persisted_new_values_by_field": {"aces": 2},
    })
    write("hourly_fallback_collection.json", {
        "attempts": 3, "endpoints": {"/extras": {"200_data": 2}},
    })
    write("extras_readback.json", {
        "status": "VERIFIED", "persisted_matches": 1, "persisted_new_marker_count": 2,
    })
    run = build_run(tmp_path, "1", "1", NOW, True)
    assert run["totals"]["attempts"] == 5
    assert run["totals"]["verified_attempts"] == 2
    assert run["totals"]["incomplete_runs"] == 1
    assert run["totals"]["fields_per_1000"] == 1000
    assert run["totals"]["paid_fields_per_1000"] == 500
    assert run["totals"]["conflicts"] == {"statistics": 1}
    write("hourly_fallback_collection.json", {
        "attempts": 3, "endpoints": {"/extras": {"200_data": 3}},
    })
    run = build_run(tmp_path, "1", "1", NOW, True)
    assert run["totals"]["verified_attempts"] == 5
    assert run["totals"]["incomplete_runs"] == 0
    assert run["totals"]["extras_markers_per_1000"] == 400
    assert aggregate([])["fields_per_1000"] is None


def test_private_storage_deduplicates_attempts_and_bounds_14_day_window(monkeypatch):
    from datetime import timedelta
    from types import SimpleNamespace

    from azure.core.exceptions import ResourceExistsError
    from tbt.services import hourly_collection

    class Container:
        def __init__(self):
            self.rows = {}

        def get_blob_client(self, container, name):
            def upload(payload, overwrite):
                assert not overwrite
                if name in self.rows:
                    raise ResourceExistsError()
                self.rows[name] = payload

            return SimpleNamespace(upload_blob=upload)

        def list_blobs(self, name_starts_with):
            return [SimpleNamespace(name=name, last_modified=NOW)
                    for name in self.rows if name.startswith(name_starts_with)]

        def download_blob(self, name, max_concurrency):
            return SimpleNamespace(readall=lambda: self.rows[name])

        def get_container_client(self, _):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    container = Container()
    monkeypatch.setattr(hourly_collection, "_blob_service", lambda: container)
    start = NOW - timedelta(days=14)
    for run_id, attempt, ended in (
        (1, 1, start), (1, 1, NOW), (1, 2, NOW),
        (2, 1, start - timedelta(seconds=1)),
    ):
        hourly_collection.publish_run({
            "run_id": run_id, "attempt": attempt, "ended_at": ended.isoformat(),
            "phases": {"primary": {"verified": False, "attempts": 2}},
            "totals": {"attempts": 2, "incomplete_runs": 1},
        })
    overview = hourly_collection.load_overview(NOW)
    assert overview["runs"] == 2
    assert overview["attempts"] == 4
    assert overview["incomplete_runs"] == 2
    assert [row["attempt"] for row in overview["recent"]] == [2, 1]
