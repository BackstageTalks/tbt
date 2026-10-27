"""Stage 1 persisted evidence, and stage 2 automatic shadow gates."""
from datetime import datetime, timezone, timedelta
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


@pytest.mark.parametrize('action', ['prepare_inputs', 'refresh_tests', 'audit_shadow'])
def test_expired_unclaimed_readonly_request_can_be_cancelled(action):
    table = Table()
    old = (datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
    request = {'id': 'e'*24, 'action': action, 'snapshot_at': old, 'created_at': old}
    with patch.object(lab, '_table', return_value=table):
        lab._put('active', request)
        lab._put('snapshot', source_snapshot())
        assert lab.status()['operation']['state'] == 'EXPIRED_UNCLAIMED'
        outcome = lab.acknowledge_failed({'action': 'acknowledge_failed', 'id': request['id']})
        assert outcome['state'] == 'EXPIRED_UNCLAIMED_CANCELLED'
        assert lab._json('active') is None
        assert lab._json('claim-'+request['id'])['cancelled'] is True
        assert lab._json('last')['id'] == request['id']


@pytest.mark.parametrize('condition', ['claimed', 'fresh', 'writer', 'stale_snapshot', 'invalid_time'])
def test_expired_cancel_never_releases_unverified_or_writer_operation(condition):
    table = Table()
    old = (datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
    request = {'id': 'e'*24, 'action': 'prepare_inputs', 'snapshot_at': old, 'created_at': old}
    snapshot = source_snapshot()
    if condition == 'fresh': request['snapshot_at'] = snapshot['observed_at']
    if condition == 'writer': request['action'] = 'promote_production'
    if condition == 'stale_snapshot': snapshot['observed_at'] = old
    if condition == 'invalid_time': request['snapshot_at'] = 'unknown'
    with patch.object(lab, '_table', return_value=table):
        lab._put('active', request)
        lab._put('snapshot', snapshot)
        if condition == 'claimed': lab._create('claim-'+request['id'], {'created_at': old})
        with pytest.raises(model_training.TrainingBlocked):
            lab.acknowledge_failed({'action': 'acknowledge_failed', 'id': request['id']})
        assert lab._json('active') == request


def test_cancel_loses_atomic_claim_race_and_keeps_operation():
    table = Table()
    old = (datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
    request = {'id': 'e'*24, 'action': 'prepare_inputs', 'snapshot_at': old, 'created_at': old}
    with patch.object(lab, '_table', return_value=table):
        lab._put('active', request)
        lab._put('snapshot', source_snapshot())
        with patch.object(lab, '_create', side_effect=model_training.TrainingBlocked('worker won')):
            with pytest.raises(model_training.TrainingBlocked):
                lab.acknowledge_failed({'action': 'acknowledge_failed', 'id': request['id']})
        assert lab._json('active') == request


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
             "artifact_verified": False,
             "preflight_report": {"eligible_rows": 600000, "tours": {
                 "atp": {"eligible_matches": 350000},
                 "wta": {"eligible_matches": 250000},
             }}},
        ]
        with pytest.raises(model_training.TrainingBlocked):
            lab.sync(finished)
        assert lab._json("active") is not None
        assert lab._json("last_preflight") is None
        assert lab._json("last")["state"] == "VERIFICATION_FAILED"
        finished["runs"]["prepare_inputs"][0]["artifact_verified"] = True
        lab.sync(finished)
        assert lab._json("active") is None
        assert lab.status()["last_preflight"]["state"] == "WORKFLOW_VERIFIED"


def test_unverifiable_readonly_preflight_can_be_acknowledged_and_retried():
    table = Table()
    with patch.object(lab, "_table", return_value=table), \
         patch.object(lab, "training_status", return_value={"can_start": True}):
        lab._put("snapshot", source_snapshot())
        queued = lab.start({"action": "prepare_inputs"}, "admin")
        lab.sync(source_snapshot())
        finished = source_snapshot()
        finished["runs"]["prepare_inputs"] = [{
            "id": 123, "status": "completed", "conclusion": "success",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "display_title": "Prepare " + queued["id"], "artifact_verified": False}]
        with pytest.raises(model_training.TrainingBlocked):
            lab.sync(finished)
        assert lab.acknowledge_failed({"action": "acknowledge_failed", "id": queued["id"]})["state"] == "FAILED_ACKNOWLEDGED"
        assert lab.start({"action": "prepare_inputs"}, "admin")["state"] == "QUEUED"


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


def test_server_rejects_shadow_training_without_verified_preflight():
    now = datetime.now(timezone.utc).isoformat()
    from tbt.services import model_training
    table = Table()
    with patch.object(lab, "_table", return_value=table), \
         patch.object(model_training, "_table", return_value=table), \
         patch.object(model_training, "status", return_value={"can_start": True, "base": "7"}):
        with pytest.raises(model_training.TrainingBlocked, match="overený audit"):
            model_training.start({"profile": "top-7.2.1", "auto_shadow": True}, "admin")
        assert (model_training.PARTITION, "request-7") not in table.rows
        lab._put("last_preflight", {
            "state": "WORKFLOW_VERIFIED", "verified_at": now,
            "run": {"status": "completed", "conclusion": "success",
                    "artifact_verified": True,
                    "preflight_report": {"eligible_rows": 600000}},
        })
        response = model_training.start({"profile": "top-7.2.1", "auto_shadow": True}, "admin")
        assert response["state"] == "QUEUED"
        assert table.rows[(model_training.PARTITION, "request-7")]["auto_shadow"] is True


def test_legacy_manual_training_never_implies_shadow():
    table = Table()
    from tbt.services import model_training
    with patch.object(lab, "_table", return_value=table), \
         patch.object(model_training, "_table", return_value=table), \
         patch.object(model_training, "status", return_value={"can_start": True, "base": "8"}):
        assert model_training.start({"profile": "top-7.2.1"}, "admin")["state"] == "QUEUED"
        assert table.rows[(model_training.PARTITION, "request-8")]["auto_shadow"] is False


def test_production_never_dispatched_from_model_factory_automation():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/protected-frozen-cdb-candidate.yml").read_text()
    worker = (root / "scripts/admin_training_worker.py").read_text()
    frontend = (root / "web/app.js").read_text()
    assert "auto_shadow" in workflow
    assert "scripts/auto_shadow_candidate.py" in workflow
    assert '"auto_shadow": "true"' in worker
    assert "confirmation!=='RELEASE '+sourceTag" in frontend
    assert "scripts/auto_promote_production" not in workflow
