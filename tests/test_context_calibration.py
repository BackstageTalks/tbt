import numpy as np
import pandas as pd
import pytest

from tbt.models.context_calibration import apply, choose, masks


def evidence(n=2000):
    frame = pd.DataFrame({'tour_atp': np.ones(n), 'tournament_level': np.full(n, .45),
                          'data_depth': np.ones(n),
                          'scheduled_at': pd.date_range('2024-01-01', periods=n, freq='h', tz='UTC')})
    p = np.full(n, .8)
    y = (np.arange(n) % 20 < 13).astype(int)
    return frame, p, y


def test_overconfidence_repaired_on_later_days_with_frozen_map():
    frame, p, y = evidence(2400)
    selected, audit = choose(frame, p, y, 1200)
    assert set(selected) == {'main_atp'}
    mapped = apply(frame, p, selected)
    assert .65 < mapped.mean() < .72
    np.testing.assert_allclose(mapped + apply(frame, 1-p, selected), 1., atol=1e-12)
    assert audit['main_atp']['public_candidate']['brier'] < audit['main_atp']['public_baseline']['brier']
    # Later labels must not alter learned parameters, even when they reject it.
    changed = y.copy(); changed[1200:] = 1
    rejected, _ = choose(frame, p, changed, 1200)
    assert rejected == {}


def test_unknown_level_is_not_treated_as_atp_and_sparse_cohort_keeps_parent():
    frame, p, y = evidence(2400)
    frame['tournament_level'] = .35
    assert not any(mask.any() for mask in masks(frame).values())
    selected, _ = choose(frame, p, y, 1200)
    assert selected == {}
    np.testing.assert_array_equal(apply(frame, p, selected), p)


def test_future_days_and_invalid_depth_fail_closed():
    frame, p, y = evidence(2400)
    with pytest.raises(ValueError, match='whole chronological'):
        choose(frame, p, y, 1201)
    frame.loc[2, 'data_depth'] = np.nan
    with pytest.raises(ValueError, match='depth'):
        choose(frame, p, y, 1200)


def test_odds_and_outcome_columns_cannot_affect_calibration():
    frame, p, y = evidence(2400)
    selected, report = choose(frame, p, y, 1200)
    frame['odds'] = 100
    frame['future_result'] = 1-y
    frame['competition'] = 'invented metadata'
    again, report2 = choose(frame, p, y, 1200)
    assert report == report2
    np.testing.assert_array_equal(apply(frame, p, selected), apply(frame, p, again))


def test_legacy_model_has_no_context_layer():
    from tbt.models.ensemble import TennisEnsemble, ProbabilityCalibrator
    model = TennisEnsemble()
    del model.context_calibrators
    model.calibrator = ProbabilityCalibrator()
    frame, p, _ = evidence()
    np.testing.assert_allclose(model._predict_with_tour_calibration(frame, p), p)


def test_candidate_fit_and_serialization_preserve_inference():
    import pickle
    from test_721_evidence_recalibration import _frames
    from tbt.models.ensemble import TennisEnsemble
    train, cal = _frames()
    for frame in (train, cal):
        frame['tour_atp'] = 1.
        frame['tournament_level'] = .45
        frame['data_depth'] = 1.
    model = TennisEnsemble(objective='log_loss')
    model.boost.set_params(max_iter=10)
    model.smooth_calibration_only = True
    model.context_calibration_selection = True
    model.fit(train, cal)
    assert 'context_calibration_validation' in model.metadata
    assert model.context_calibrators == {}  # too few earlier fit rows
    restored = pickle.loads(pickle.dumps(model))
    np.testing.assert_array_equal(model.predict_proba(cal), restored.predict_proba(cal))


def test_holdout_ablation_is_read_only_and_keeps_fixed_rows():
    from tbt.models.context_calibration import holdout_report
    frame, p, y = evidence(2400)
    maps, _ = choose(frame, p, y, 1200)
    frame['target'] = y
    calibrated = apply(frame, p, maps)
    before = calibrated.copy()
    report = holdout_report(frame, p, calibrated)
    assert report['groups']['all']['n'] == 2400
    assert report['groups']['all']['parent_anchored_bands']['0.8']['n'] == 2400
    np.testing.assert_array_equal(calibrated, before)
