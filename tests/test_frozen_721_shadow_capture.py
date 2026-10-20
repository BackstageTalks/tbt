"""Passive frozen v7.2.1 shadow must not change existing publication/paid calls."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import frozen_721_shadow_capture as capture
from tbt.services.frozen_721_research import (
    FROZEN_721_TAG, FROZEN_721_VERSION, FROZEN_721_MODEL_SHA256,
    validate_frozen_evidence,
)

PROD = "v201-20260925T204608601094Z"


def prediction(p, version, scheduled):
    return {
        "id": "future-match-1",
        "event_id": "event-future-1",
        "tour": "ATP",
        "surface": "hard",
        "tournament": "Private test",
        "scheduled_at": scheduled.isoformat(),
        "model_version": version,
        "player1": {"id": "a", "probability": p},
        "player2": {"id": "b", "probability": 1 - p},
    }


def test_opt_in_frozen_capture_writes_only_distinct_shadow_and_keeps_first_snapshot(tmp_path, monkeypatch):
    imported = []
    uploaded = []
    remote_assets = {}
    calls = []
    scheduled = datetime.now(timezone.utc) + timedelta(days=3)

    class FakeRelease:
        def __init__(self, repo, tag, directory):
            imported.append(tag)
            self.tag = tag
            self.directory = directory
            self.directory.mkdir(parents=True, exist_ok=True)

        def download(self, **kwargs):
            if self.tag == FROZEN_721_TAG:
                (self.directory / "model.joblib").write_bytes(b"synthetic candidate binary")
            else:
                assert {capture.LEDGER_ASSET, capture.REPORT_ASSET} <= set(remote_assets[self.tag])
                for name, data in remote_assets[self.tag].items():
                    (self.directory / name).write_bytes(data)

        def _asset_names(self):
            return set(remote_assets.get(self.tag, {}))

        def upload_bundle(self, paths):
            remote_assets[self.tag] = {p.name: p.read_bytes() for p in paths}
            uploaded.append((self.tag, [p.name for p in paths]))

    monkeypatch.setattr(capture, "ReleaseStore", FakeRelease)
    monkeypatch.setattr(capture, "sha256",
                        lambda data: SimpleNamespace(hexdigest=lambda: FROZEN_721_MODEL_SHA256))
    fake_candidate = SimpleNamespace(version=FROZEN_721_VERSION, fitted=True, feature_names=[])
    monkeypatch.setattr(capture, "load_model", lambda path: fake_candidate)

    def fake_predict(model, history, upcoming, **kwargs):
        calls.append("offline_prediction")
        return [prediction(0.75 if len(calls) == 1 else 0.90, FROZEN_721_VERSION, scheduled)]

    monkeypatch.setattr(capture, "predict", fake_predict)
    prod = prediction(0.60, PROD, scheduled)
    args = {
        "data_repository": "BackstageTalks/tbt-data",
        "cache": tmp_path, "champion_model": SimpleNamespace(version=PROD),
        "production_predictions": [prod], "matches": [], "upcoming": [object()],
        "prediction_now": datetime.now(timezone.utc),
    }
    first = capture.capture_frozen_721_shadow(**args)
    assert first["captured"] == 1
    assert first["remote_readback"] == "VERIFIED"
    assert first["incremental_provider_requests"] == 0
    assert first["production_mutated"] is False
    assert capture.SHADOW_TAG in imported
    assert "tbt-model-shadow-v1" not in imported
    assert len(uploaded) == 1 and uploaded[0][0] == capture.SHADOW_TAG
    private = tmp_path / "frozen-721-shadow" / capture.LEDGER_ASSET
    initial = json.loads(private.read_text())
    validate_frozen_evidence(initial, production_version=PROD)
    assert initial["rows"][0]["challenger_player1_probability"] == 0.75
    second = capture.capture_frozen_721_shadow(**args)
    assert second["captured"] == 1
    assert second["remote_readback"] == "VERIFIED"
    unchanged = json.loads(private.read_text())
    assert unchanged["rows"][0]["challenger_player1_probability"] == 0.75
    assert len(calls) == 2 and len(uploaded) == 2


def test_wrong_model_sha_aborts_before_shadow_release_or_prediction(tmp_path, monkeypatch):
    class CandidateOnly:
        def __init__(self, repo, tag, directory):
            assert tag == FROZEN_721_TAG
            self.directory = directory
            self.directory.mkdir(parents=True, exist_ok=True)

        def download(self, **kwargs):
            (self.directory / "model.joblib").write_bytes(b"wrong model")

    monkeypatch.setattr(capture, "ReleaseStore", CandidateOnly)
    monkeypatch.setattr(capture, "predict",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("No scoring")))
    import pytest
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        capture.capture_frozen_721_shadow(
            data_repository="BackstageTalks/tbt-data", cache=tmp_path,
            champion_model=SimpleNamespace(version=PROD),
            production_predictions=[], matches=[], upcoming=[],
            prediction_now=datetime.now(timezone.utc),
        )


def test_corrupt_remote_readback_cannot_be_reported_as_success(tmp_path, monkeypatch):
    import pytest

    remote_assets = {}
    scheduled = datetime.now(timezone.utc) + timedelta(days=2)

    class CorruptRelease:
        def __init__(self, repo, tag, directory):
            self.tag = tag
            self.directory = directory
            self.directory.mkdir(parents=True, exist_ok=True)

        def _asset_names(self):
            return set(remote_assets.get(self.tag, {}))

        def download(self, **kwargs):
            if self.tag == FROZEN_721_TAG:
                (self.directory / "model.joblib").write_bytes(b"synthetic candidate binary")
            else:
                for name, data in remote_assets[self.tag].items():
                    if (self.directory.name == "frozen-721-shadow-readback"
                            and name == capture.REPORT_ASSET):
                        data = b'{"corrupted":true}\\n'
                    (self.directory / name).write_bytes(data)

        def upload_bundle(self, paths):
            remote_assets[self.tag] = {p.name: p.read_bytes() for p in paths}

    monkeypatch.setattr(capture, "ReleaseStore", CorruptRelease)
    monkeypatch.setattr(capture, "sha256",
                        lambda data: SimpleNamespace(hexdigest=lambda: FROZEN_721_MODEL_SHA256))
    monkeypatch.setattr(capture, "load_model", lambda path: SimpleNamespace(
        version=FROZEN_721_VERSION, fitted=True, feature_names=[]
    ))
    monkeypatch.setattr(capture, "predict", lambda *a, **kw: [
        prediction(0.72, FROZEN_721_VERSION, scheduled)
    ])
    with pytest.raises(RuntimeError, match="remote shadow read-back mismatch"):
        capture.capture_frozen_721_shadow(
            data_repository="BackstageTalks/tbt-data", cache=tmp_path,
            champion_model=SimpleNamespace(version=PROD),
            production_predictions=[prediction(0.6, PROD, scheduled)],
            matches=[], upcoming=[object()],
            prediction_now=datetime.now(timezone.utc),
        )


def test_refresh_trigger_enables_frozen_shadow_without_statistics_side_effects():
    from pathlib import Path
    text = Path(".github/workflows/data.yml").read_text(encoding="utf-8")
    line = next(x for x in text.splitlines()
                if "BLINQ_FROZEN_721_SHADOW_ENABLED:" in x)
    assert "github.event_name == 'push'" in line
    assert "contains(github.event.head_commit.message, '[refresh-now]')" in line
    assert "inputs.mode == 'refresh'" in line
    assert "inputs.mode == 'current-refresh'" in line
    assert "inputs.mode == 'statistics'" not in line
