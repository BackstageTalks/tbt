import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
import download_tennis_history as downloader
from tbt.data.history_snapshot import load_partitions


def test_manual_per_run_cap_has_no_rolling_reservation_and_parquet_is_saved(monkeypatch, match_factory, tmp_path):
    events = []

    class Store:
        def __init__(self, *args):
            pass

        def download(self):
            pass

        def upload_bundle(self, paths):
            self.upload(paths)

        def upload(self, paths):
            for path in paths:
                assert path.is_file()
            events.extend(path.name for path in paths)

    class Provider:
        def __init__(self, request_budget):
            assert request_budget is None
            self.request_count = 0
            self.request_limit = None
            self.client = SimpleNamespace(close=lambda: None)

        def matches_for_day(self, tour, day, historical):
            assert self.request_limit == 100
            self.request_count += 1
            events.append("api-call")
            return [match_factory(tour, "A", "B", "A", tour=tour)]

    monkeypatch.setattr(downloader, "ReleaseStore", Store)
    monkeypatch.setattr(downloader, "RapidTennisClient", Provider)
    monkeypatch.setattr(downloader, "settings", replace(downloader.settings, rapidapi_key="test"))
    monkeypatch.setattr("sys.argv", ["download", "--start", "2025-01-01", "--end", "2025-01-01",
        "--history-dir", str(tmp_path), "--max-requests", "100", "--publish", "--data-repository", "test/private"])
    downloader.main()

    assert not (tmp_path / "request_budget.json").exists()
    assert len(load_partitions(tmp_path)) == 2
    report = json.loads((tmp_path / "download_report.json").read_text())
    assert report["requests_including_retries"] == 2
    assert report["completed_days"] == 1
    assert events.index("history-2025.parquet") > events.index("api-call")


def test_public_data_repository_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr("release_store.gh", lambda *args: json.dumps({"visibility": "PUBLIC"}))
    with pytest.raises(ValueError, match="PRIVATE"):
        downloader.ReleaseStore("test/public", "tbt-data-v1", tmp_path)



def test_primary_provider_error_survives_final_checkpoint_failure(monkeypatch, tmp_path):
    class Store:
        def __init__(self, *args):
            pass
        def download(self):
            pass
        def upload_bundle(self, paths):
            raise RuntimeError("checkpoint-upload-failed")

    class Provider:
        def __init__(self, request_budget):
            self.request_count = 1
            self.request_limit = None
            self.client = SimpleNamespace(close=lambda: None)

    def fail_download(*args, **kwargs):
        raise RuntimeError("provider-primary-error")

    monkeypatch.setattr(downloader, "ReleaseStore", Store)
    monkeypatch.setattr(downloader, "RapidTennisClient", Provider)
    monkeypatch.setattr(downloader, "download_days", fail_download)
    monkeypatch.setattr(downloader, "settings", replace(downloader.settings, rapidapi_key="test"))
    monkeypatch.setattr("sys.argv", [
        "download", "--start", "2025-01-01", "--end", "2025-01-01",
        "--history-dir", str(tmp_path), "--max-requests", "100",
        "--publish", "--data-repository", "test/private",
    ])

    with pytest.raises(RuntimeError, match="provider-primary-error") as caught:
        downloader.main()
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "checkpoint-upload-failed" in str(caught.value.__cause__)
    report = json.loads((tmp_path / "download_report.json").read_text())
    assert report["checkpoint_failed"] == 1
