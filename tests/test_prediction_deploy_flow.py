from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import confirm_prediction_publication as confirm
import prepare_feed
from tbt.services.feed import empty_feed


def _valid_feed(event_id="event-1"):
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=2)).isoformat()
    row = {
        "id": "match-1",
        "event_id": event_id,
        "tour": "ATP",
        "scheduled_at": future,
        "tournament": "Test Open",
        "surface": "hard",
        "round": "R1",
        "competition": "atp",
        "quality": {},
        "player1": {"id": "A", "name": "A", "probability": 0.7},
        "player2": {"id": "B", "name": "B", "probability": 0.3},
        "winner_id": "A",
        "confidence": 0.7,
        "data_depth": 10,
        "stats_available": False,
        "signals": [],
        "model_version": "test",
        "created_at": now.isoformat(),
        "issued_at": None,
        "publication_status": "pending",
        "result": None,
    }
    return {
        "schema": 1,
        "generated_at": now.isoformat(),
        "model": {"version": "test"},
        "upcoming": [row],
        "results": [],
        "performance": {},
        "history": {},
        "ready": True,
    }


def _ledger_for_feed(feed):
    return [dict(row) for row in feed["upcoming"]]


def test_prepare_feed_with_no_candidate_overwrites_stale_checked_in_feed(monkeypatch, tmp_path):
    target = tmp_path / "api/data/feed.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(_valid_feed("stale")))

    class Store:
        def __init__(self, *args):
            pass
        def _asset_names(self):
            return set()
        def download(self, *args, **kwargs):
            raise AssertionError("download must not run without a candidate")

    monkeypatch.setattr(prepare_feed, "ROOT", tmp_path)
    monkeypatch.setattr(prepare_feed, "ReleaseStore", Store)
    monkeypatch.setenv("GH_TOKEN", "token")
    prepare_feed.main()
    assert json.loads(target.read_text()) == empty_feed()


def test_prepare_feed_requires_prediction_asset_pair_and_keeps_ledger_out_of_api(monkeypatch, tmp_path):
    class Store:
        def __init__(self, repository, tag, directory):
            self.directory = Path(directory)
        def _asset_names(self):
            return {"feed.json", "ledger.json", "_tbt_bundle_manifest.json"}
        def download(self, extra_names=(), required_names=()):
            assert set(required_names) == {"feed.json", "ledger.json"}
            self.directory.mkdir(parents=True, exist_ok=True)
            feed = _valid_feed()
            (self.directory / "feed.json").write_text(json.dumps(feed))
            (self.directory / "ledger.json").write_text(json.dumps(_ledger_for_feed(feed)))

    monkeypatch.setattr(prepare_feed, "ROOT", tmp_path)
    monkeypatch.setattr(prepare_feed, "ReleaseStore", Store)
    monkeypatch.setenv("GH_TOKEN", "token")
    prepare_feed.main()
    assert (tmp_path / "api/data/feed.json").is_file()
    assert not (tmp_path / "api/data/ledger.json").exists()


def test_prepare_feed_fails_closed_on_half_prediction_release(monkeypatch, tmp_path):
    class Store:
        def __init__(self, *args):
            pass
        def _asset_names(self):
            return {"feed.json"}

    monkeypatch.setattr(prepare_feed, "ROOT", tmp_path)
    monkeypatch.setattr(prepare_feed, "ReleaseStore", Store)
    monkeypatch.setenv("GH_TOKEN", "token")
    with pytest.raises(FileNotFoundError, match="ledger.json"):
        prepare_feed.main()


def test_confirm_no_candidate_is_noop_only_for_empty_deployment(monkeypatch, tmp_path):
    class Store:
        def __init__(self, *args):
            pass
        def _asset_names(self):
            return set()
        def download(self, *args, **kwargs):
            raise AssertionError("download must not run without a candidate")

    monkeypatch.setattr(confirm, "ROOT", tmp_path)
    monkeypatch.setattr(confirm, "ReleaseStore", Store)
    deployed = tmp_path / "empty.json"
    deployed.write_text(json.dumps(empty_feed()))
    confirm.main(["--data-repository", "test/private", "--deployed-feed", str(deployed)])

    deployed.write_text(json.dumps(_valid_feed("unverifiable")))
    with pytest.raises(RuntimeError, match="No private prediction candidate"):
        confirm.main(["--data-repository", "test/private", "--deployed-feed", str(deployed)])


def test_confirm_complete_candidate_requires_exact_deployed_feed(monkeypatch, tmp_path):
    feed = _valid_feed()
    ledger = _ledger_for_feed(feed)
    uploaded = []

    class Store:
        def __init__(self, repository, tag, directory):
            self.directory = Path(directory)
        def _asset_names(self):
            return {"feed.json", "ledger.json", "_tbt_bundle_manifest.json"}
        def download(self, extra_names=(), required_names=()):
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / "feed.json").write_text(json.dumps(feed))
            (self.directory / "ledger.json").write_text(json.dumps(ledger))
        def upload_bundle(self, paths):
            uploaded.extend(Path(p).name for p in paths)

    monkeypatch.setattr(confirm, "ROOT", tmp_path)
    monkeypatch.setattr(confirm, "ReleaseStore", Store)
    deployed = tmp_path / "deployed.json"
    deployed.write_text(json.dumps(feed))
    confirm.main(["--data-repository", "test/private", "--deployed-feed", str(deployed)])
    assert uploaded == ["ledger.json"]
    confirmed = json.loads((tmp_path / ".cache/tbt/predictions-confirm/ledger.json").read_text())
    assert confirmed[0]["issued_at"] is not None

    changed = dict(feed)
    changed["generated_at"] = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    deployed.write_text(json.dumps(changed))
    with pytest.raises(RuntimeError, match="does not match"):
        confirm.main(["--data-repository", "test/private", "--deployed-feed", str(deployed)])


def test_prepare_feed_rejects_same_event_with_different_pick(monkeypatch, tmp_path):
    feed = _valid_feed()
    ledger = _ledger_for_feed(feed)
    ledger[0]["winner_id"] = "B"
    ledger[0]["player1"] = {**ledger[0]["player1"], "probability": 0.2}
    ledger[0]["player2"] = {**ledger[0]["player2"], "probability": 0.8}

    class Store:
        def __init__(self, repository, tag, directory):
            self.directory = Path(directory)
        def _asset_names(self):
            return {"feed.json", "ledger.json", "_tbt_bundle_manifest.json"}
        def download(self, **kwargs):
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / "feed.json").write_text(json.dumps(feed))
            (self.directory / "ledger.json").write_text(json.dumps(ledger))

    monkeypatch.setattr(prepare_feed, "ROOT", tmp_path)
    monkeypatch.setattr(prepare_feed, "ReleaseStore", Store)
    monkeypatch.setenv("GH_TOKEN", "token")
    with pytest.raises(RuntimeError, match="feed/ledger mismatch"):
        prepare_feed.main()


def test_confirm_rejects_same_event_with_different_ledger_pick(monkeypatch, tmp_path):
    feed = _valid_feed()
    ledger = _ledger_for_feed(feed)
    ledger[0]["winner_id"] = "B"
    ledger[0]["player1"] = {**ledger[0]["player1"], "probability": 0.2}
    ledger[0]["player2"] = {**ledger[0]["player2"], "probability": 0.8}
    uploaded = []

    class Store:
        def __init__(self, repository, tag, directory):
            self.directory = Path(directory)
        def _asset_names(self):
            return {"feed.json", "ledger.json", "_tbt_bundle_manifest.json"}
        def download(self, **kwargs):
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / "feed.json").write_text(json.dumps(feed))
            (self.directory / "ledger.json").write_text(json.dumps(ledger))
        def upload_bundle(self, paths):
            uploaded.extend(paths)

    monkeypatch.setattr(confirm, "ROOT", tmp_path)
    monkeypatch.setattr(confirm, "ReleaseStore", Store)
    deployed = tmp_path / "deployed.json"
    deployed.write_text(json.dumps(feed))
    with pytest.raises(RuntimeError, match="feed/ledger mismatch"):
        confirm.main(["--data-repository", "test/private", "--deployed-feed", str(deployed)])
    assert uploaded == []
