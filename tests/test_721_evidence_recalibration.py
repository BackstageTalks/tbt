"""v7.2.1 calibration repair must learn from outcomes, never exclude by odds."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from tbt.models.ensemble import ProbabilityCalibrator, TennisEnsemble
from tbt.models.feature_builder import FEATURE_NAMES
from tbt.models.symmetry import swap_frame


def _frames():
    rng = np.random.default_rng(721)
    n = 800
    frame = pd.DataFrame({name: rng.normal(size=n) for name in FEATURE_NAMES})
    frame["stats_known_both"] = np.arange(n) % 2
    frame["rank_known_both"] = (np.arange(n) // 2) % 2
    frame["elo_probability"] = 1 / (1 + np.exp(-frame.elo_diff))
    frame["target"] = rng.binomial(1, frame.elo_probability)
    frame["match_id"] = [f"pit-721-{i}" for i in range(n)]
    frame["scheduled_at"] = [
        datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=i // 4)
        for i in range(n)
    ]
    return frame.iloc[:440].copy(), frame.iloc[440:].copy()


def test_721_candidate_smooth_probability_calibration_and_symmetry():
    train, cal = _frames()
    model = TennisEnsemble(objective="log_loss")
    model.boost.set_params(max_iter=10)
    model.smooth_calibration_only = True
    model.evidence_calibration_selection = True
    model.fit(train, cal)
    assert model.metadata["smooth_calibration_only"] is True
    assert model.calibrator.kind in {"identity", "platt"}
    assert "isotonic" not in model.metadata["calibration_candidates"]
    brier = model.metadata["smooth_calibration_brier_candidates"]
    assert set(brier) >= {"identity"}
    assert model.calibrator.kind == "identity" or (
        brier[model.calibrator.kind] <= brier["identity"] + 1e-12
    )
    assert "evidence_calibration_validation" in model.metadata
    assert set(model.metadata["evidence_calibration_validation"]) == {
        "stats_0_rank_0", "stats_0_rank_1", "stats_1_rank_0", "stats_1_rank_1"
    }
    assert all(v["status"] == "INSUFFICIENT_DISJOINT_CALIBRATION"
               for v in model.metadata["evidence_calibration_validation"].values())
    original = model.predict_proba(cal)
    reverse = model.predict_proba(swap_frame(cal))
    assert np.isfinite(original).all()
    np.testing.assert_allclose(original + reverse, 1., atol=1e-10)


def test_721_tour_selection_does_not_recreate_isotonic_plateaus():
    rng = np.random.default_rng(7001)
    n = 2000
    raw = rng.uniform(.05, .95, n)
    labels = rng.binomial(1, raw)
    tours = (np.arange(n) % 2).astype(float)
    result, report = TennisEnsemble._choose_tour_calibrators(
        raw, labels, tours, 1000, ProbabilityCalibrator(), allow_isotonic=False
    )
    assert set(report) == {"atp", "wta"}
    assert all(row["kind"] in {"identity", "platt"}
               for item in report.values() for row in item.get("alternatives", []))
    assert all(x.kind in {"identity", "platt"} for x in result.values())


def test_evidence_override_compares_to_best_existing_calibrator_not_raw_global():
    rng = np.random.default_rng(171)
    n = 7200
    raw = rng.uniform(.03, .97, n)
    flags = (np.arange(n) % 4 == 0)
    frame = pd.DataFrame({
        "stats_known_both": flags.astype(float),
        "rank_known_both": np.where(flags, 0., 1.),
    })
    p_true = np.where(flags, .5 + .20 * (raw - .5), raw)
    labels = rng.binomial(1, p_true)
    split = 3960
    selected, _ = TennisEnsemble._choose_evidence_calibrators(
        raw, labels, frame, split, ProbabilityCalibrator(),
    )
    assert "stats_1_rank_0" in selected

    # A tour-specific winner calibration is ALREADY close to the true rate.
    # A redundant evidence override should not replace that winning baseline.
    old_baseline = np.where(flags, p_true, raw)
    preserved, audit = TennisEnsemble._choose_evidence_calibrators(
        raw, labels, frame, split, ProbabilityCalibrator(),
        baseline_probabilities=old_baseline,
    )
    assert "stats_1_rank_0" not in preserved
    assert audit["stats_1_rank_0"]["status"] == "GLOBAL_RETAINED"


def test_721_training_profile_wires_pit_evidence_without_changing_old_champion():
    source = Path("api/tbt/services/training.py").read_text()
    assert 'training_profile in {"top-7.2.1", "accuracy-7.2.2"}' in source
    assert 'evaluation_model.evidence_calibration_selection = (' in source
    assert 'evaluation_model.smooth_calibration_only = training_profile == "top-7.2.1"' in source
    assert '"pit_evidence_holdout": paired_evidence_holdout_diagnostics(' in source
    # No model-version mutation or odds/canonical writer was introduced.
    legacy = TennisEnsemble()
    assert not getattr(legacy, "smooth_calibration_only", False)
    assert legacy.evidence_calibrators == {}
