"""Candidate-only chronological training-weight validation; no CDB/API fixtures."""
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from tbt.models.ensemble import TennisEnsemble
from tbt.models.symmetry import swap_frame


def sample(n=780):
    rng = np.random.default_rng(722)
    elo_diff = rng.normal(size=n)
    p = 1 / (1 + np.exp(-elo_diff))
    return pd.DataFrame({
        "elo_diff": elo_diff,
        "elo_probability": p,
        "target": (rng.random(n) < p).astype(int),
        "match_id": [f"fixture-{i}" for i in range(n)],
        "scheduled_at": pd.date_range("2024-01-01", periods=n, freq="12h", tz="UTC"),
    })


def test_weights_are_fit_cutoff_relative_and_mean_normalized():
    train = sample(600)
    w, proof = TennisEnsemble._age_sample_weights(train, 180)
    assert proof["half_life_days"] == 180
    assert np.isclose(w.mean(), 1)
    assert w[-1] > w[0] > 0
    shifted = train.copy()
    shifted["scheduled_at"] = shifted["scheduled_at"] + timedelta(days=500)
    w_shifted, _ = TennisEnsemble._age_sample_weights(shifted, 180)
    assert np.allclose(w, w_shifted)


def test_same_weights_go_to_both_orientations_and_both_estimators(monkeypatch):
    train = sample(330)
    model = TennisEnsemble(feature_names=["elo_diff"])
    observed = {}
    def linear_fit(x, y, **kwargs):
        observed["linear"] = (x, y, kwargs)
    def boost_fit(x, y, **kwargs):
        observed["boost"] = (x, y, kwargs)
    monkeypatch.setattr(model.linear, "fit", linear_fit)
    monkeypatch.setattr(model.boost, "fit", boost_fit)
    model._fit_estimators(train, 365)
    xl, yl, kl = observed["linear"]
    xb, yb, kb = observed["boost"]
    assert xl.shape == xb.shape == (660, 1)
    assert np.array_equal(yl[:330], 1 - yl[330:])
    assert np.array_equal(yl, yb)
    assert np.allclose(kl["model__sample_weight"], kl["scale__sample_weight"])
    assert np.allclose(kl["model__sample_weight"], kb["sample_weight"])
    assert np.allclose(kb["sample_weight"][:330], kb["sample_weight"][330:])


def test_invalid_half_life_fails_closed():
    with pytest.raises(ValueError, match="Unsupported"):
        TennisEnsemble._age_sample_weights(sample(300), 90)
    invalid = sample(300)
    invalid.loc[0, "scheduled_at"] = pd.NaT
    with pytest.raises(ValueError, match="timestamps"):
        TennisEnsemble._age_sample_weights(invalid, 365)


def test_train_only_variant_selection_and_weighted_swap_symmetry():
    frame = sample()
    train, calibration = frame.iloc[:600].copy(), frame.iloc[600:].copy()
    model = TennisEnsemble(feature_names=["elo_diff"], objective="log_loss")
    model.boost.set_params(max_iter=8)
    model.time_decay_variant_search = True
    model.fit(train, calibration)
    audit = model.metadata["training_weight_selection"]
    assert audit["status"] in {"BASELINE_RETAINED", "TRAIN_ONLY_SELECTED"}
    assert audit["holdout_used"] is False
    assert audit["market_odds_used"] is False
    assert audit["validation_start_utc"] < calibration.scheduled_at.min().isoformat()
    assert audit["selected_half_life_days"] in (None, 180, 365)
    assert model.metadata["training_weighting"]["half_life_days"] == audit["selected_half_life_days"]
    predictions = model.predict_proba(calibration)
    assert np.allclose(
        predictions + model.predict_proba(swap_frame(calibration)), 1, atol=1e-12
    )


def test_frozen_refit_uses_exact_selected_half_life():
    frame = sample()
    train, calibration = frame.iloc[:600].copy(), frame.iloc[600:].copy()
    model = TennisEnsemble(feature_names=["elo_diff"])
    model.boost.set_params(max_iter=8)
    model.fit_frozen(
        train, calibration, blend_weight=.5, elo_weight=0.,
        calibrator_kind="identity", training_half_life_days=365,
    )
    assert model.metadata["training_weighting"]["half_life_days"] == 365
    assert model.training_half_life_days == 365
    assert np.allclose(
        model.predict_proba(calibration) +
        model.predict_proba(swap_frame(calibration)), 1, atol=1e-12
    )
