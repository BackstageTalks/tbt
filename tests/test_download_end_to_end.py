import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
import download_tennis_history as downloader
from tbt.data.history_snapshot import load_partitions


def test_release_reservation_precedes_calls_and_parquet_is_saved(monkeypatch, match_factory, tmp_path):
    events = []
    class Store:
        def __init__(self, *args):
            pass
        def download(self):
            pass
        def upload(self, paths):
            for path in paths:
                assert path.is_file()
            events.extend(path.name for path in paths)
    class Provider:
        def __init__(self, request_budget):
            self.budget = request_budget
            self.request_count = 0
            self.client = SimpleNamespace(close=lambda: None)
        def matches_for_day(self, tour, day, historical):
            assert events[0] == "request_budget.json"
            self.budget()
            self.request_count += 1
            events.append("api-call")
            return [match_factory(tour, "A", "B", "A", tour=tour)]
    monkeypatch.setattr(downloader, "ReleaseStore", Store)
    monkeypatch.setattr(downloader, "RapidTennisClient", Provider)
    monkeypatch.setattr(downloader, "settings", replace(downloader.settings, rapidapi_key="test"))
    monkeypatch.setattr("sys.argv", ["download", "--start", "2025-01-01", "--end", "2025-01-01",
        "--history-dir", str(tmp_path), "--max-requests", "100", "--publish", "--data-repository", "test/private"])
    downloader.main()
    assert len(load_partitions(tmp_path)) == 2
    report = json.loads((tmp_path / "download_report.json").read_text())
    assert report["requests_including_retries"] == 2
    assert report["completed_days"] == 1
    assert events.index("history-2025.parquet") > events.index("api-call")


def test_public_data_repository_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr("release_store.gh", lambda *args: json.dumps({"visibility": "PUBLIC"}))
    with pytest.raises(ValueError, match="PRIVATE"):
        downloader.ReleaseStore("test/public", "tbt-data-v1", tmp_path)

