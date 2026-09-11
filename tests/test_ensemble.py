from datetime import datetime, timedelta, timezone

import joblib
import numpy as np
import pandas as pd
import pytest

from tbt.models.ensemble import TennisEnsemble, calibration_split
from tbt.models.feature_builder import FEATURE_NAMES, FeatureBuilder
from tbt.models.symmetry import swap_frame


def frames():
    rng = np.random.default_rng(12)
    n = 600
    frame = pd.DataFrame({name: rng.normal(size=n) for name in FEATURE_NAMES})
    frame["elo_probability"] = 1 / (1 + np.exp(-frame.elo_diff))
    frame["target"] = (rng.random(n) < frame.elo_probability).astype(int)
    frame["match_id"] = [f"m{i}" for i in range(n)]
    frame["scheduled_at"] = [datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=i // 4) for i in range(n)]
    return frame.iloc[:400].copy(), frame.iloc[400:].copy()


@pytest.fixture(scope="module")
def fitted():
    train, cal = frames()
    model = TennisEnsemble()
    model.boost.set_params(max_iter=12)
    model.fit(train, cal)
    return model, cal


def test_model_and_loaded_artifact_are_symmetric(fitted, tmp_path):
    model, cal = fitted
    p = model.predict_proba(cal)
    assert np.allclose(p + model.predict_proba(swap_frame(cal)), 1, atol=1e-12)
    path = tmp_path / "model.joblib"
    joblib.dump(model, path)
    assert np.allclose(joblib.load(path).predict_proba(cal), p)
    assert model.metadata["objective"] == "accuracy"


def test_real_feature_snapshots_obey_swap_contract(match_factory):
    builder = FeatureBuilder()
    builder.replay([match_factory("a", "A", "C", "A", day=1), match_factory("b", "B", "D", "D", day=2)])
    match = match_factory("next", "A", "B", None, day=5)
    forward = pd.DataFrame([builder.snapshot(match)])
    reverse = pd.DataFrame([builder.snapshot(match.swapped())])
    assert np.allclose(swap_frame(forward)[FEATURE_NAMES], reverse[FEATURE_NAMES])


def test_calibrator_split_does_not_cut_day():
    _, cal = frames()
    split = calibration_split(cal)
    assert cal.iloc[split - 1].scheduled_at.date() < cal.iloc[split].scheduled_at.date()
    cal["scheduled_at"] = cal.iloc[0].scheduled_at
    assert calibration_split(cal) is None


def test_overlapping_training_is_rejected():
    train, cal = frames()
    cal["scheduled_at"] = train.iloc[-1].scheduled_at
    with pytest.raises(ValueError, match="disjoint whole UTC days"):
        TennisEnsemble().fit(train, cal)


def test_duplicate_training_is_rejected():
    train, cal = frames()
    train.loc[1, "match_id"] = train.iloc[0].match_id
    with pytest.raises(ValueError, match="Duplicate"):
        TennisEnsemble().fit(train, cal)


def test_unverified_archive_weather_cannot_change_predictions(fitted):
    model, cal = fitted
    changed = cal.copy()
    changed["weather_serve_interaction"] = 100000
    assert np.allclose(model.predict_proba(cal), model.predict_proba(changed))


def test_legacy_champion_keeps_original_prediction_path(fitted):
    import copy
    model, cal = fitted
    legacy = copy.deepcopy(model)
    legacy.metadata = {}
    del legacy.excluded_features
    linear, boost = legacy._raw_pair(legacy._matrix(cal))
    expected = np.clip(legacy.calibrator.predict(legacy._blend(linear, boost)), .01, .99)
    assert np.allclose(legacy.predict_proba(cal), expected)
