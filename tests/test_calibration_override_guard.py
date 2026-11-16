"""A pooled score improvement must not bypass the high-confidence guard."""
import numpy as np
import pandas as pd

from tbt.models.ensemble import ProbabilityCalibrator, TennisEnsemble


def conflicting_cohort():
    # Sharpening helps the numerous .62 fixtures but harms .8 fixtures.
    # Repeat identical rates on disjoint fit/selection slices, both orientations.
    raw = np.r_[np.full(1600, .62), np.full(400, .8)]
    y = np.r_[np.tile([1] * 9 + [0], 160), np.tile([1, 1, 1, 0, 0], 80)]
    raw, y = np.r_[raw, 1 - raw], np.r_[y, 1 - y]
    return np.tile(raw, 2), np.tile(y, 2), len(raw)


def test_tour_override_cannot_hide_high_confidence_regression():
    raw, y, split = conflicting_cohort()
    tours = np.ones(len(raw))
    baseline = ProbabilityCalibrator()
    old, _ = TennisEnsemble._choose_tour_calibrators(
        raw, y, tours, split, baseline, allow_isotonic=False)
    assert "atp" in old  # Demonstrates the previous bypass.
    guarded, audit = TennisEnsemble._choose_tour_calibrators(
        raw, y, tours, split, baseline, allow_isotonic=False,
        protect_high_confidence=True)
    assert "atp" not in guarded
    check = audit["atp"]["high_confidence_validation"]["platt"]
    assert check["rows"] == 800
    assert not check["approved"]
    assert check["scores"]["override"]["brier_score"] > check["scores"]["identity"]["brier_score"]


def test_evidence_override_cannot_hide_high_confidence_regression():
    raw, y, split = conflicting_cohort()
    frame = pd.DataFrame({"stats_known_both": np.ones(len(raw)),
                          "rank_known_both": np.zeros(len(raw))})
    old, _ = TennisEnsemble._choose_evidence_calibrators(
        raw, y, frame, split, ProbabilityCalibrator())
    assert "stats_1_rank_0" in old
    guarded, audit = TennisEnsemble._choose_evidence_calibrators(
        raw, y, frame, split, ProbabilityCalibrator(), protect_high_confidence=True)
    assert "stats_1_rank_0" not in guarded
    check = audit["stats_1_rank_0"]["high_confidence_validation"]
    assert check["selected_methods"] == ["identity"]


def test_accepted_override_retains_exact_validated_parameters():
    # Earlier outcomes justify shrinking .8 to .6. Later outcomes favor .5,
    # so fitting again would change the very map the guard evaluated.
    raw = np.tile(np.r_[np.full(500, .8), np.full(500, .2)], 2)
    y = np.r_[np.tile([1, 1, 1, 0, 0], 100), np.tile([1, 1, 0, 0, 0], 100),
              np.tile([1, 0], 500)]
    split = 1000
    early = TennisEnsemble._fit_calibrator("platt", raw[:split], y[:split])
    selected, audit = TennisEnsemble._choose_tour_calibrators(
        raw, y, np.ones(len(raw)), split, ProbabilityCalibrator(),
        allow_isotonic=False, protect_high_confidence=True)
    assert "atp" in selected
    np.testing.assert_allclose(selected["atp"].model.coef_, early.model.coef_)
    frame = pd.DataFrame({"stats_known_both": np.ones(len(raw)),
                          "rank_known_both": np.zeros(len(raw))})
    selected, audit = TennisEnsemble._choose_evidence_calibrators(
        raw, y, frame, split, ProbabilityCalibrator(), protect_high_confidence=True)
    np.testing.assert_allclose(selected["stats_1_rank_0"].model.coef_, early.model.coef_)
    assert audit["stats_1_rank_0"]["refit_on_selection"] is False


def test_smooth_fit_never_refits_global_map_on_selection_outcomes(monkeypatch):
    from tests.test_721_evidence_recalibration import _frames
    from tbt.models.ensemble import calibration_split

    train, cal = _frames()
    lengths = []
    original = TennisEnsemble._fit_calibrator

    def recording_fit(kind, p, y):
        lengths.append(len(p))
        return original(kind, p, y)

    monkeypatch.setattr(TennisEnsemble, "_fit_calibrator", staticmethod(recording_fit))
    model = TennisEnsemble(objective="log_loss")
    model.boost.set_params(max_iter=10)
    model.smooth_calibration_only = True
    model.fit(train, cal)
    assert lengths and max(lengths) == calibration_split(cal)
    assert model.metadata["calibration_refit_on_selection"] is False
