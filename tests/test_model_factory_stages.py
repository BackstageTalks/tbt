"""Stage 1 persisted evidence, and stage 2 automatic shadow gates."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import sys
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "scripts"),
                str(Path(__file__).resolve().parents[1] / "api")]

from tbt.services import model_lab as lab
from tbt.services import model_training
from auto_shadow_candidate import offline_gate


class Table:
    def __init__(self):
        self.rows = {}

    def get_entity(self, *, partition_key, row_key):
        return self.rows[(partition_key, row_key)]

    def upsert_entity(self, entity, mode=None):
        self.rows[(entity["PartitionKey"], entity["RowKey"])] = dict(entity)

    def create_entity(self, entity):
        key = (entity["PartitionKey"], entity["RowKey"])
        if key in self.rows:
            raise ValueError("Duplicate operation")
        self.rows[key] = dict(entity)

    def delete_entity(self, *, partition_key, row_key):
        self.rows.pop((partition_key, row_key))


def source_snapshot():
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "can_start": True,
        "reason": "OK",
        "active_sha256": "a" * 64,
        "champion_sha256": "b" * 64,
        "candidates": [],
        "runs": {action: [] for action in lab.WORKFLOWS},
    }


def test_stage1_preflight_is_queued_once_and_requires_remote_artifact():
    table = Table()
    with patch.object(lab, "_table", return_value=table), \
         patch.object(lab, "training_status", return_value={"can_start": True}):
        lab._put("snapshot", source_snapshot())
        request = lab.start({"action": "prepare_inputs"}, "admin")
        assert request["state"] == "QUEUED"
        with pytest.raises(model_training.TrainingBlocked):
            lab.start({"action": "prepare_inputs"}, "admin")
        lab.sync(source_snapshot())  # one-shot claim
        cmd = lab._json("active")
        finished = source_snapshot()
        finished["can_start"] = False
        finished["runs"]["prepare_inputs"] = [
            {"id": 123, "status": "completed", "conclusion": "success",
             "created_at": datetime.now(timezone.utc).isoformat(),
             "display_title": "Prepare " + cmd["id"],
             "artifact_verified": False},
        ]
        with pytest.raises(model_training.TrainingBlocked):
            lab.sync(finished)
        assert lab._json("active") is not None
        assert lab._json("last_preflight") is None
        finished["runs"]["prepare_inputs"][0]["artifact_verified"] = True
        lab.sync(finished)
        assert lab._json("active") is None
        assert lab.status()["last_preflight"]["state"] == "WORKFLOW_VERIFIED"


def test_shadow_requires_materially_higher_accuracy_and_gate_pass():
    base = {
        "holdout": {"accuracy": 0.675, "n": 250},
        "production_holdout": {"accuracy": 0.65, "n": 250},
        "evaluation_governance": {"holdout_fingerprint": "pinned"},
        "immutable_training_backup": {"candidate_tag": "blinq-candidate-frozen-123-1"},
        "promotion_decision": {"promotion_requested": False},
    }
    cert = {
        "status": "VERIFIED_FULL_INPUTS_AND_ISOLATED_RESTORE",
        "champion_restore": {"status": "PASS"},
        "candidate_tag": "blinq-candidate-frozen-123-1",
    }
    with patch("auto_shadow_candidate._promotion_metric_gate", return_value=(True, [])):
        assert offline_gate(base, cert) == (True, [])
        poor = dict(base, holdout={"accuracy": 0.651, "n": 250})
        ok, reasons = offline_gate(poor, cert)
        assert not ok and "insufficient_accuracy_gain_for_automatic_shadow" in reasons
        wrong = dict(cert, candidate_tag="different")
        ok, reasons = offline_gate(base, wrong)
        assert not ok and "candidate_training_source_mismatch" in reasons
    with patch("auto_shadow_candidate._promotion_metric_gate",
               return_value=(False, ["wta_segment_regression"])):
        ok, reasons = offline_gate(base, cert)
        assert not ok and "wta_segment_regression" in reasons


def test_production_never_dispatched_from_model_factory_automation():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/protected-frozen-cdb-candidate.yml").read_text()
    worker = (root / "scripts/admin_training_worker.py").read_text()
    frontend = (root / "web/app.js").read_text()
    assert "auto_shadow" in workflow
    assert "scripts/auto_shadow_candidate.py" in workflow
    assert '"auto_shadow": "true"' in worker
    assert "data-admin-action=\"model-factory-promote\" disabled" in frontend
    assert "scripts/auto_promote_production" not in workflow
