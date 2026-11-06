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



def test_721_tour_evidence_selection_baseline_never_trains_on_later_labels():
    """An already refitted serving map cannot validate a nested cohort map."""
    rng = np.random.default_rng(72109)
    n, split = 1800, 1000
    raw = rng.uniform(.05, .95, n)
    targets = rng.binomial(1, raw)
    tours = (np.arange(n) % 2).astype(float)
    atp_early = np.flatnonzero(tours[:split] == 1.)
    atp_all = np.flatnonzero(tours == 1.)
    global_map = ProbabilityCalibrator()
    # Simulate the production-ready tour map, trained on every calibration row.
    serving_map = TennisEnsemble._fit_calibrator("platt", raw[atp_all],
                                                  targets[atp_all])
    approved = {"atp": serving_map}
    before = TennisEnsemble._selection_tour_baseline(
        raw, targets, tours, split, global_map, approved
    )
    revised = targets.copy()
    revised[split:] = 1 - revised[split:]
    after = TennisEnsemble._selection_tour_baseline(
        raw, revised, tours, split, global_map, approved
    )
    # Validation-period results must not influence the benchmark probabilities.
    np.testing.assert_allclose(before, after, atol=1e-12)
    expected_early = TennisEnsemble._fit_calibrator(
        "platt", raw[atp_early], targets[atp_early]
    )
    np.testing.assert_allclose(
        before[tours == 1.],
        TennisEnsemble._calibrated(expected_early, raw[tours == 1.]),
        atol=1e-12,
    )
    # The unselected tour still uses the earlier global method.
    np.testing.assert_allclose(before[tours == 0.], raw[tours == 0.], atol=1e-12)


def test_721_tour_baseline_rejects_missing_or_non_pit_selection_evidence():
    rng = np.random.default_rng(72110)
    raw = rng.uniform(.05, .95, 900)
    labels = rng.binomial(1, raw)
    tours = (np.arange(900) % 2).astype(float)
    selected = {"atp": TennisEnsemble._fit_calibrator(
        "platt", raw[tours == 1.], labels[tours == 1.])}
    with np.testing.assert_raises_regex(ValueError, "point-in-time"):
        bad_tours = tours.copy()
        bad_tours[2] = np.nan
        TennisEnsemble._selection_tour_baseline(
            raw, labels, bad_tours, 550, ProbabilityCalibrator(), selected,
        )
    with np.testing.assert_raises_regex(ValueError, "Insufficient earlier"):
        TennisEnsemble._selection_tour_baseline(
            raw, labels, tours, 100, ProbabilityCalibrator(), selected,
        )
