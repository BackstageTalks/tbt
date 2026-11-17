import numpy as np
import pandas as pd
import pytest

from tbt.models.context_calibration import apply, choose, masks, scores


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
    again, report2 = choose(frame, p, y, 1200)
    assert report == report2
    np.testing.assert_array_equal(apply(frame, p, selected), apply(frame, p, again))


def test_explicit_competition_resolves_lossy_generic_level_without_gender_guess():
    frame, _, _ = evidence(4)
    frame['tournament_level'] = .35
    frame['competition'] = ['ATP', 'UTR Men', 'WTA 125', 'unknown']
    assert masks(frame)['main_atp'].tolist() == [True, False, False, False]
    frame['competition'] = ['ITF Men', 'ITF Women', 'Challenger', 'ATP Finals']
    assert masks(frame)['itf_atp'].tolist() == [True, True, False, False]
    assert masks(frame)['challenger_atp'].tolist() == [False, False, True, False]


def test_competition_masks_accept_read_only_pandas_arrays(monkeypatch):
    original = pd.Series.to_numpy

    def readonly(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        result.setflags(write=False)
        return result

    frame, _, _ = evidence(3)
    frame['competition'] = ['ATP', 'ATP', 'WTA']
    frame['tournament'] = ['ATP 250', 'ITF M15', 'WTA 500']
    monkeypatch.setattr(pd.Series, 'to_numpy', readonly)
    groups = masks(frame)
    assert groups['main_atp'].tolist() == [True, False, False]
    assert groups['itf_atp'].tolist() == [False, True, False]



def test_context_rejects_generic_atp_level_when_tournament_is_lower_tier():
    frame, _, _ = evidence(6)
    frame['tournament_level'] = .35
    frame['competition'] = ['ATP', 'ATP', 'ATP', 'ATP', 'WTA', 'ATP']
    frame['tournament'] = ['ITF M15', 'UTR Men', 'Challenger Bratislava',
                           'ATP 250 Brisbane', 'WTA 125', 'Exhibition']
    groups = masks(frame)
    assert groups['itf_atp'].tolist() == [True, False, False, False, False, False]
    assert groups['challenger_atp'].tolist() == [False, False, True, False, False, False]
    assert groups['main_atp'].tolist() == [False, False, False, True, False, False]


def test_confidence_ece_detects_misleading_zero_overall_confidence_gap():
    # Equal overconfidence/underconfidence in adjacent bins cancel at the
    # aggregate mean; reliability ECE must still catch each bin separately.
    p = np.r_[np.full(200, .65), np.full(200, .85)]
    y = np.r_[np.r_[np.ones(170), np.zeros(30)],
              np.r_[np.ones(130), np.zeros(70)]].astype(int)
    result = scores(p, y)
    assert result['confidence_gap'] == pytest.approx(0)
    assert result['confidence_ece_10'] == pytest.approx(.2)



def test_tail_rank_cannot_receive_unproved_confidence_boost():
    frame, probabilities, _ = evidence(2400)
    probabilities[:] = .7
    y = (np.arange(2400) % 20 < 17).astype(int)  # 85% wins, true base underconfidence
    # Without a tail-specific evidence gate, the broad main-tour map would be
    # allowed to boost all fixtures because the disjoint validation is strong.
    general, _ = choose(frame, probabilities, y, 1200)
    assert 'main_atp' in general

    frame['atp_hist_known_both'] = 1.
    frame['atp_hist_worst_rank_log'] = np.log1p(50.)
    frame.loc[1200:1249, 'atp_hist_worst_rank_log'] = np.log1p(2500.)
    protected, report = choose(frame, probabilities, y, 1200)
    assert protected == {}
    tail = report['main_atp']['rank_tail_validation']['tail_rank']
    assert tail['n'] == 50
    assert tail['status'] == 'INSUFFICIENT_EVIDENCE'
    assert tail['no_boost'] is False
    assert report['main_atp']['status'] == 'PARENT_RETAINED'


def test_missing_weekly_ranks_need_separate_evidence_for_confidence_boost():
    frame, probabilities, _ = evidence(2400)
    probabilities[:] = .7
    y = (np.arange(2400) % 20 < 17).astype(int)
    frame['atp_hist_known_both'] = 1.
    frame['atp_hist_worst_rank_log'] = np.log1p(50.)
    frame.loc[1200:1239, 'atp_hist_known_both'] = 0.
    frame.loc[1200:1239, 'atp_hist_worst_rank_log'] = 0.
    protected, report = choose(frame, probabilities, y, 1200)
    assert protected == {}
    missing = report['main_atp']['rank_tail_validation']['weekly_rank_missing']
    assert missing['n'] == 40
    assert missing['no_boost'] is False

def test_context_selection_reports_only_chronologically_validated_shrinkage():
    frame, p, y = evidence(2400)
    chosen, audit = choose(frame, p, y, 1200)
    main = audit['main_atp']
    assert len(main['validated_shrink_options']) == 2
    assert main['choice_never_uses_final_holdout'] is True
    assert all(option['weight'] > 0 for option in main['validated_shrink_options'])
    assert ('main_atp' in chosen) == (main['status'] == 'SELECTED')
    if 'main_atp' in chosen:
        assert chosen['main_atp'].weight == pytest.approx(main['shrink_weight'])


def test_conflicting_competition_gender_is_not_main_tour_evidence():
    frame, _, _ = evidence(3)
    frame['competition'] = ['WTA 500', 'ATP 250', 'Grand Slam']
    frame['tournament'] = ['WTA 500', 'ATP 250', 'Australian Open']
    groups = masks(frame)
    assert groups['main_atp'].tolist() == [False, True, True]

def test_legacy_model_has_no_context_layer():
    from tbt.models.ensemble import TennisEnsemble, ProbabilityCalibrator
    model = TennisEnsemble()
    del model.context_calibrators
    model.calibrator = ProbabilityCalibrator()
    frame, p, _ = evidence()
    np.testing.assert_allclose(model._predict_with_tour_calibration(frame, p), p)



def test_context_calibration_cannot_vanish_during_serving_refit():
    # Previously fit_frozen() reset context_calibrators={} without warning,
    # so a subsequently promoted model could silently lose its approved map.
    from types import SimpleNamespace
    from tbt.services.training import TrainingResult, refit_serving_model
    selected = SimpleNamespace(context_calibrators={"main_atp": object()})
    result = TrainingResult(model=selected, report={}, feature_frame=pd.DataFrame())
    with pytest.raises(ValueError, match="refusing to discard validated probability maps"):
        refit_serving_model(result)


def test_pit_rank_source_is_not_inferred_from_current_tournament_label():
    from tbt.services.training import _pit_rank_snapshot
    # A generic ATP label or present-day rank cannot recover a missing
    # previous-week source: this would fake evidence at the exact 2500-rank
    # edge where the user reported bad confidence.
    with pytest.raises(ValueError, match="Missing frozen weekly"):
        _pit_rank_snapshot({"tour": "ATP", "player1_rank": 2500}, "atp")

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
