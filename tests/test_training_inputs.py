import numpy as np
import pandas as pd
import pytest

from tbt.services.training_inputs import input_diagnostics, require_informative_inputs
from tbt.services.training import _new_production_ensemble


def sample():
    return pd.DataFrame({
        "tour": ["atp", "atp", "wta", "wta"],
        "atp_hist_rank_advantage": [0.1, 0.2, 0, 0],
        "wta_hist_rank_advantage": [0, 0, 0.2, 0.3],
        "serve_quality_diff": [0.1, 0.2, 0.1, 0.3],
        "return_quality_diff": [0.2, 0.4, 0.1, 0.2],
    })


def diagnostics(train, calibration):
    return input_diagnostics({"train": train, "calibration": calibration}, list(train.columns[1:]))


def test_verified_weekly_rank_features_can_replace_dead_legacy_rank():
    frame = sample()
    report = diagnostics(frame, frame)
    require_informative_inputs(report)
    assert report["train"]["wta"]["features"]["wta_hist_rank_advantage"]["distinct"] == 2


def test_live_calibration_does_not_hide_dead_training_serve():
    train, cal = sample(), sample()
    train["serve_quality_diff"] = 0.0
    with pytest.raises(ValueError, match="train/atp: dead serve_quality_diff"):
        require_informative_inputs(diagnostics(train, cal))


def test_atp_coverage_does_not_hide_dead_wta_return():
    frame = sample()
    frame.loc[frame.tour == "wta", "return_quality_diff"] = 0
    with pytest.raises(ValueError, match="train/wta: dead return_quality_diff"):
        require_informative_inputs(diagnostics(frame, frame))


def test_nonfinite_inputs_are_refused_before_imputation():
    frame = sample()
    frame.loc[0, "serve_quality_diff"] = np.inf
    with pytest.raises(ValueError, match="nonfinite inputs"):
        require_informative_inputs(diagnostics(frame, frame))


def test_probability_objective_is_opt_in():
    assert _new_production_ensemble().objective == "accuracy"
    assert _new_production_ensemble(objective="log_loss").objective == "log_loss"


def test_721_fit_preserves_probability_profile_and_separate_market_gate():
    from datetime import datetime, timedelta, timezone
    from tbt.schemas import MatchRecord
    from tbt.services.training import train_from_matches
    rng = np.random.default_rng(721)
    matches = []
    for i in range(1200):
        a, b = map(int, rng.choice(20, 2, replace=False))
        at = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i // 4)
        matches.append(MatchRecord(
            match_id=str(i), tour="atp" if i % 2 else "wta", scheduled_at=at,
            player1_id=str(a), player2_id=str(b), player1_name=str(a), player2_name=str(b),
            player1_rank=a + 1, player2_rank=b + 1,
            winner_id=str(a if rng.random() < 0.5 else b), surface="hard",
            provider_payload={"_tbt_rank_provenance": {
                "point_in_time": True, "source": "synthetic-test", "as_of": (at-timedelta(days=1)).isoformat(),
            }},
            stats={"p1_service_points_won": 0.5+a/100, "p2_service_points_won": 0.5+b/100,
                   "p1_return_points_won": 0.5-b/100, "p2_return_points_won": 0.5-a/100},
        ))
    result = train_from_matches(matches, min_matches=1000, training_profile="top-7.2.1")
    assert result.model.version.startswith("v7.2.1-")
    assert result.model.objective == "log_loss"
    assert result.model.metadata["objective"] == "log_loss"
    assert result.model.metadata["independent_serve_return"] is True
    assert result.model.metadata["independent_direct_rates"] is True
    assert result.report["optimization_objective"] == "log_loss"
    assert result.report["top_market_validation"]["promotion_ready_for_top"] is False
    assert result.report["input_diagnostics"]["train"]["wta"]["features"]["rank_advantage"]["distinct"] > 1
