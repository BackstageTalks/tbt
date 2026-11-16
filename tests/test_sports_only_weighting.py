"""Nonpromoting sport-only model training variant; no CDB, odds or API."""
import numpy as np
import pandas as pd
import pytest

from tbt.models.ensemble import TennisEnsemble
from tbt.services.training import train_from_matches


def frame():
    return pd.DataFrame({
        "competition": [
            "ATP", "WTA", "Challenger", "WTA 125", "ITF W35",
            "ITF M25", "UTR", "unknown", None, "main_tour",
            "ATP Futures", "ATP Challenger", "ITF ATP",
        ],
        "tour": ["atp", "wta", "atp", "wta", "wta", "atp", "atp",
                 "wta", "wta", "atp", "atp", "atp", "atp"],
    })


def test_predeclared_tour_2x_reweights_only_reliable_main_competition():
    model = TennisEnsemble()
    model.sports_sample_weight_profile = "main_tour_2x"
    weights = model._sports_fit_weights(frame())
    assert list(weights) == [2., 2., 2., 2., 1., 1., 1.,
                             1., 1., 2., 1., 2., 1.]
    assert len(weights) == 13


def test_default_inference_fitting_keeps_exact_unweighted_path():
    model = TennisEnsemble()
    assert model.sports_sample_weight_profile == "none"
    assert model._sports_fit_weights(frame()) is None


def test_unsupported_or_missing_competition_fails_closed():
    model = TennisEnsemble()
    model.sports_sample_weight_profile = "invalid"
    with pytest.raises(ValueError, match="Unknown sports"):
        model._sports_fit_weights(frame())
    model.sports_sample_weight_profile = "main_tour_2x"
    with pytest.raises(ValueError, match="Competition"):
        model._sports_fit_weights(frame()[["tour"]])


def test_training_rejects_nonprotected_or_unknown_sports_experiment():
    with pytest.raises(ValueError, match="Unknown sports"):
        train_from_matches([], min_matches=1, training_profile="top-7.2.1",
                           sports_weight_profile="random-profile")
    with pytest.raises(ValueError, match="only valid"):
        train_from_matches([], min_matches=1, training_profile="standard",
                           sports_weight_profile="main_tour_2x")


def test_sports_weights_ignore_results_probs_and_bookmaker_inputs():
    f = frame()
    model = TennisEnsemble()
    model.sports_sample_weight_profile = "main_tour_2x"
    original = model._sports_fit_weights(f)
    modified = f.assign(target=np.arange(len(f)) % 2,
                        odds_player1=np.linspace(1.1, 4, len(f)),
                        ev=np.linspace(-1, 1, len(f)),
                        elo_probability=np.linspace(.1, .9, len(f)))
    assert np.array_equal(original, model._sports_fit_weights(modified))
