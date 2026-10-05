import numpy as np

from audit_court_speed_ablation import decision


def test_decision_keeps_only_clear_paired_improvement():
    clear = decision({
        "second_minus_first_log_loss": -0.01,
        "approximate_paired_95pct_interval": [-0.02, -0.001],
    })
    assert clear["verdict"] == "KEEP_CANDIDATE"

    uncertain = decision({
        "second_minus_first_log_loss": -0.001,
        "approximate_paired_95pct_interval": [-0.01, 0.008],
    })
    assert uncertain["verdict"] == "HOLD_RESEARCH"

    worse = decision({
        "second_minus_first_log_loss": 0.01,
        "approximate_paired_95pct_interval": [0.001, 0.02],
    })
    assert worse["verdict"] == "DROP"


def test_decision_drops_non_improving_direction_even_if_uncertain():
    result = decision({
        "second_minus_first_log_loss": 0.0001,
        "approximate_paired_95pct_interval": [-0.005, 0.006],
    })
    assert result["verdict"] == "DROP"


def test_court_speed_swap_contract_is_explicit_and_symmetric():
    import pandas as pd
    from tbt.data.court_speed import COURT_SPEED_FEATURE_NAMES
    from tbt.models.ensemble import TennisEnsemble
    from tbt.models.symmetry import swap_frame

    frame = pd.DataFrame([{
        "court_speed_prior": 101.0,
        "court_speed_current": 104.0,
        "court_speed_delta_vs_venue_history": 3.0,
        "player_perf_fast_courts": 0.2,
        "player_perf_slow_courts": -0.1,
        "court_speed_mismatch_player1": 0.3,
        "court_speed_mismatch_player2": 0.7,
        "court_speed_known": 1.0,
        "target": 1,
    }])
    swapped = swap_frame(frame)
    assert swapped.loc[0, "court_speed_prior"] == 101.0
    assert swapped.loc[0, "court_speed_current"] == 104.0
    assert swapped.loc[0, "court_speed_delta_vs_venue_history"] == 3.0
    assert swapped.loc[0, "court_speed_known"] == 1.0
    assert swapped.loc[0, "player_perf_fast_courts"] == -0.2
    assert swapped.loc[0, "player_perf_slow_courts"] == 0.1
    assert swapped.loc[0, "court_speed_mismatch_player1"] == 0.7
    assert swapped.loc[0, "court_speed_mismatch_player2"] == 0.3
    assert swapped.loc[0, "target"] == 0

    model = TennisEnsemble(feature_names=COURT_SPEED_FEATURE_NAMES)
    assert model.feature_names == COURT_SPEED_FEATURE_NAMES
