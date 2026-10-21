"""v7.2.1 candidate improvements select tour calibration only on disjoint cal days."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tbt.models.ensemble import TennisEnsemble, ProbabilityCalibrator


def test_wta_overconfidence_can_be_corrected_without_holdout_or_future_results():
    rng = np.random.default_rng(721)
    n, split = 2400, 1320
    raw = rng.uniform(.06, .94, n)
    tours = (np.arange(n) % 2 == 0).astype(float)
    # ATP forecasts are well calibrated; WTA overconfidence needs shrinkage.
    true_p = np.where(tours == 1., raw, .5 + .22 * (raw - .5))
    targets = rng.binomial(1, true_p)
    selected, evidence = TennisEnsemble._choose_tour_calibrators(
        raw, targets, tours, split, ProbabilityCalibrator(),
    )
    assert evidence["wta"]["status"] == "SELECTED"
    assert evidence["wta"]["global_selection_log_loss"] > (
        evidence["wta"]["best_selection_log_loss"] + .008
    )
    assert selected["wta"].kind in {"platt", "isotonic"}
    assert evidence["wta"]["fit_n"] >= 250
    assert evidence["wta"]["selection_n"] >= 120


def test_small_tour_groups_keep_shared_global_calibrator():
    rng = np.random.default_rng(12)
    raw = rng.uniform(.1, .9, 400)
    targets = rng.binomial(1, raw)
    tours = np.r_[np.ones(380), np.zeros(20)]
    selected, evidence = TennisEnsemble._choose_tour_calibrators(
        raw, targets, tours, 260, ProbabilityCalibrator(),
    )
    assert selected == {}
    assert evidence["wta"]["status"] == "INSUFFICIENT_DISJOINT_CALIBRATION"
    assert evidence["atp"]["status"] == "GLOBAL_RETAINED"  # enough rows, no improvement margin


def test_candidate_subgroup_inference_is_symmetry_preserving_and_legacy_safe():
    class Shrink:
        kind = "custom"
        def predict(self, p):
            return .5 + .5 * (np.asarray(p) - .5)

    model = TennisEnsemble()
    model.fitted = True
    model.metadata["symmetric_inference"] = True
    model._raw = lambda frame: np.array([.8, .8, .2, .2])
    frame = pd.DataFrame({"tour_atp": [1., 0., 1., 0.]})
    model.tour_calibrators = {"wta": Shrink()}
    actual = model.predict_proba(frame)
    np.testing.assert_allclose(actual, [.8, .65, .2, .35])
    # Existing serialized champion (without the new attribute) retains the
    # exact prior global-calibrator inference path.
    del model.tour_calibrators
    np.testing.assert_allclose(model.predict_proba(frame), [.8, .8, .2, .2])


def test_tour_calibration_fails_closed_on_bad_schema():
    with pytest.raises(ValueError):
        TennisEnsemble._choose_tour_calibrators(
            np.array([.3, .7]), np.array([0, 1]),
            np.array([float("nan"), 1.]), 1, ProbabilityCalibrator(),
        )


def test_legacy_champion_has_no_tour_feature_requirement():
    model = TennisEnsemble()
    model.tour_calibrators = {}
    p = model._predict_with_tour_calibration(pd.DataFrame(), np.array([.2, .8]))
    np.testing.assert_allclose(p, [.2, .8])


def test_retraining_is_one_shot_nonpromoting_and_backup_gated():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/protected-frozen-cdb-candidate.yml").read_text()
    assert "api/tbt/models/ensemble.py" in workflow
    assert "startsWith(github.event.head_commit.message" in workflow
    assert "feat(721): one-shot candidate-only tour calibration study" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "python scripts/guarded_candidate_backup.py prepare" in workflow
    assert "python scripts/audit_training_leakage.py" in workflow
    assert "BLINQ_RAPIDAPI_MAX_RPS: '0'" in workflow
    assert "No --promote" in workflow
    assert "python scripts/guarded_candidate_backup.py verify" in workflow
    assert "python scripts/cdb_global_writer_lock.py acquire" in workflow
    assert "python scripts/cdb_global_writer_lock.py release --if-held" in workflow
    assert "  schedule:" not in workflow


def test_wta_tour_calibrator_requires_both_proper_scores_on_calibration_only():
    approved = TennisEnsemble._tour_calibration_approved
    # Lower log loss alone is not enough on WTA.
    assert not approved("wta", "platt", "identity", .500, .520, .250, .240)
    assert approved("wta", "platt", "identity", .500, .520, .230, .240)
    # ATP must now satisfy both proper scores, just like WTA.
    assert not approved("atp", "platt", "identity", .500, .520, .250, .240)
    assert approved("atp", "platt", "identity", .500, .520, .230, .240)
    assert not approved("wta", "identity", "identity", .480, .520, .220, .240)
    assert not approved("wta", "platt", "identity", .515, .520, .230, .240)
    assert not approved("atp", "platt", "identity", .515, .520, .230, .240)
    assert not approved("atp", "identity", "identity", .480, .520, .220, .240)
