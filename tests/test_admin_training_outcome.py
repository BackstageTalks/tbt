"""The Admin must distinguish a saved candidate from a verified shadow write."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from tbt.services import model_training as training
from scripts import auto_shadow_candidate as shadow


RUN = {"id": 123, "run_attempt": 2, "head_sha": "c" * 40}


def outcome():
    return {"schema": 1, "run_id": "123", "run_attempt": "2", "code_sha": "c" * 40,
            "candidate_tag": "blinq-candidate-frozen-123-2", "state": "SHADOW_BLOCKED",
            "production_mutated": False, "remote_readback": None,
            "reasons": ["top_market_validation_required"]}


def mock_artifact(monkeypatch, payload):
    monkeypatch.setattr(training, "github", lambda path: {"artifacts": [
        {"name": "model-factory-outcome-123-2", "expired": False}]})
    def download(args, **kwargs):
        directory = Path(args[args.index("-D") + 1])
        (directory / "model-factory-outcome.json").write_text(json.dumps(payload), encoding="utf-8")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(training.subprocess, "run", download)


def test_downloaded_blocked_outcome_retains_reasons(monkeypatch):
    mock_artifact(monkeypatch, outcome())
    assert training._read_shadow_outcome(RUN) == outcome()


@pytest.mark.parametrize("field,value", [
    ("run_id", "999"), ("run_attempt", "1"), ("code_sha", "d" * 40),
    ("candidate_tag", "blinq-candidate-frozen-123-1"), ("production_mutated", True),
    ("state", "PROMOTED"), ("reasons", "not a list"),
])
def test_wrong_run_or_unsafe_report_is_rejected(monkeypatch, field, value):
    mock_artifact(monkeypatch, {**outcome(), field: value})
    with pytest.raises(training.TrainingUnavailable):
        training._read_shadow_outcome(RUN)


def test_success_requires_independent_shadow_readback(monkeypatch):
    payload = {**outcome(), "state": "SHADOW_ACTIVE", "reasons": []}
    mock_artifact(monkeypatch, payload)
    with pytest.raises(training.TrainingUnavailable):
        training._read_shadow_outcome(RUN)
    payload["remote_readback"] = "VERIFIED"
    mock_artifact(monkeypatch, payload)
    assert training._read_shadow_outcome(RUN)["state"] == "SHADOW_ACTIVE"


def test_older_run_has_no_invented_outcome(monkeypatch):
    monkeypatch.setattr(training, "github", lambda path: {"artifacts": []})
    assert training._read_shadow_outcome(RUN) is None


def test_writer_pins_exact_attempt_and_never_claims_promotion(tmp_path, monkeypatch):
    monkeypatch.setattr(shadow, "ROOT", tmp_path)
    for key, value in {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_SHA": "c" * 40}.items():
        monkeypatch.setenv(key, value)
    shadow.write_outcome({"candidate_tag": "blinq-candidate-frozen-123-2"},
                         "SHADOW_BLOCKED", ["top_market_validation_required"])
    saved = json.loads((tmp_path / ".cache/tbt/training-backup/model-factory-outcome.json").read_text())
    assert saved == outcome()


def test_missing_model_is_not_listed_as_complete(monkeypatch):
    monkeypatch.setattr(training, "inspect", lambda: {"runs": []})
    monkeypatch.setattr(training, "github", lambda path: [
        {"tag_name": "blinq-candidate-frozen-123-2", "html_url": "", "assets": []},
        {"tag_name": "blinq-candidate-frozen-122-1", "html_url": "", "assets": [
            {"name": n, "size": 10} for n in ("model.joblib", "training_report.json", "_tbt_bundle_manifest.json")]},
    ])
    records = training.collect_status()["candidates"]
    assert [r["complete"] for r in records] == [False, True]


def test_worker_subscribes_to_preflight_completion_and_syncs_after_error():
    text = Path(".github/workflows/admin-training-worker.yml").read_text(encoding="utf-8")
    assert "BlinQ Model Factory source preflight" in text
    assert "if: ${{ !cancelled() }}" in text
