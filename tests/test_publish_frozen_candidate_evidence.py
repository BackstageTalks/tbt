"""Fail-closed regression tests for immutable candidate-evidence persistence."""
import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import publish_frozen_candidate_evidence as evidence


COMMIT = "a" * 40
BLOB = "b" * 40


def _stub(monkeypatch, *, changed=False, wrong_blob=False, missing_ref=False):
    observations = []
    stored = {}

    def inspect(*args, **kwargs):
        assert len(args) == 1 and args[0][:2] == ["gh", "api"]
        return SimpleNamespace(returncode=1, stderr="HTTP 404", stdout="")

    def api(*args, input=None):
        observations.append(args)
        if "--method" in args:
            body = json.loads(input)
            stored["body"] = body
            return json.dumps({
                "commit": {} if missing_ref else {"sha": COMMIT},
                "content": {"sha": BLOB},
            })
        assert args[2] == (
            f"repos/{evidence.DATA_REPO}/contents/{evidence.PRIVATE_PATH}"
            f"?ref={COMMIT}"
        )
        raw = base64.b64decode(stored["body"]["content"])
        if changed:
            raw += b"corruption"
        return json.dumps({
            "sha": "c" * 40 if wrong_blob else BLOB,
            "encoding": "base64",
            "content": base64.b64encode(raw).decode(),
        })

    monkeypatch.setattr(evidence.subprocess, "run", inspect)
    monkeypatch.setattr(evidence, "run", api)
    return observations


def test_candidate_evidence_uses_commit_pinned_independent_readback(monkeypatch):
    calls = _stub(monkeypatch)
    payload = {"run_id": 123, "comparison": {"sample_size": 500}}
    raw = (json.dumps(payload, ensure_ascii=False, indent=2,
                      sort_keys=True, allow_nan=False) + "\n").encode()
    assert evidence.persist_verified(payload) == hashlib.sha256(raw).hexdigest()
    assert len(calls) == 2
    assert "--method" in calls[0]
    assert "?ref=" + COMMIT in calls[1][-1]


@pytest.mark.parametrize("failure, message", [
    ({"changed": True}, "readback mismatch"),
    ({"wrong_blob": True}, "blob identity mismatch"),
    ({"missing_ref": True}, "no immutable readback reference"),
])
def test_candidate_evidence_fails_closed(monkeypatch, failure, message):
    _stub(monkeypatch, **failure)
    with pytest.raises(RuntimeError, match=message):
        evidence.persist_verified({"run_id": 123})


def test_empty_governed_holdout_is_deferred_not_fabricated(tmp_path):
    binary = tmp_path / "model.joblib"
    binary.write_bytes(b"candidate")
    cert = {"champion_version": "old", "candidate_tag": "blinq-candidate-frozen-1-1"}
    report = {"production_holdout": {}, "holdout": {}, "data": {"holdout": 0},
              "promotion_decision": {"promotion_requested": False, "eligible": False,
                                     "production_version": "old", "candidate_version": "new"},
              "evaluation_governance": {"eligibility_reason": "previous_decision_cutoff_unknown",
                                        "holdout_fingerprint": ""}}
    result = evidence.make_evidence(cert, report, binary)
    assert result["status"] == "EVALUATION_DEFERRED"
    assert result["comparison"] == {"sample_size": 0}
    assert result["model_promoted"] is False
    report["evaluation_governance"]["eligibility_reason"] = "unexpected_corruption"
    with pytest.raises(ValueError):
        evidence.make_evidence(cert, report, binary)
    report["promotion_decision"]["production_version"] = "wrong"
    with pytest.raises(ValueError, match="champion"):
        evidence.make_evidence(cert, report, binary)
