"""Fail-closed source-label audit before any 7.2.1 model fit/cache publish."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_training_leakage import _binary_training_targets  # noqa: E402


@pytest.mark.parametrize("targets,valid", [
    ([0, 1, 0, 1], True),
    (["0", "1", "0"], True),
    ([0, 1, 0.5], False),
    ([0, 1, 1.9], False),
    ([0, 1, -1], False),
    ([0, 1, 2], False),
    ([0, 1, None], False),
    ([0, 1, float("nan")], False),
    ([0, 1, float("inf")], False),
    (["0", "1", "not-an-outcome"], False),
    ([], False),
])
def test_leakage_audit_never_truncates_or_silently_drops_invalid_targets(targets, valid):
    result, observed = _binary_training_targets(pd.DataFrame({"target": targets}))
    assert result is valid
    if targets and valid:
        assert observed == [0, 1]
    if 0.5 in targets:
        assert 0.5 in observed


def test_leakage_audit_rejects_missing_target_column():
    assert _binary_training_targets(pd.DataFrame({"match_id": ["m1"]})) == (False, [])



def test_721_one_shot_audit_patch_retrains_only_under_existing_gates():
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/protected-frozen-cdb-candidate.yml").read_text()
    assert "      - scripts/audit_training_leakage.py" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "'feat(721): one-shot candidate-only tour calibration study'" in workflow
    assert "python scripts/audit_training_leakage.py" in workflow
    assert "python scripts/guarded_candidate_backup.py verify" in workflow
    assert "python scripts/cdb_global_writer_lock.py acquire" in workflow
    assert "# No --promote." in workflow
