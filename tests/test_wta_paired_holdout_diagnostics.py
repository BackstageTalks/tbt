"""Read-only WTA attribution on the same untouched candidate/champion rows."""
import numpy as np
import pandas as pd
import pytest

from tbt.services.training import paired_wta_holdout_diagnostics


def test_paired_wta_diagnostics_never_mix_atp_or_call_it_calibration():
    n = 120
    data = pd.DataFrame({
        "tour_atp": [0.] * 90 + [1.] * 30,
        "target": [int(i % 2 == 0) for i in range(n)],
        "stats_known_both": [.0] * 40 + [1.] * 80,
        "wta_hist_known_both": [.0] * 60 + [1.] * 60,
        "wta_season_stats_known_both": [.0] * 45 + [1.] * 75,
        "break_point_serve_diff": [.0] * 40 + [.1] * 80,
        "break_point_return_diff": [.0] * n,
    })
    champion = np.array([.7 if y else .3 for y in data.target])
    candidate = champion.copy()
    candidate[40:90] = .50
    result = paired_wta_holdout_diagnostics(data, candidate, champion)
    assert result["n"] == 90
    assert result["full_wta"]["n"] == 90
    assert result["availability_cohorts"]["stats_known_both"]["missing"]["n"] == 40
    assert result["full_wta"]["delta"]["brier_score"] > 0
    assert result["break_point_signal"]["break_point_return_diff"]["status"] == "NONZERO_SIGNAL_NOT_COVERAGE"
    assert result["never_select_model_on_this_holdout"] is True


def test_paired_wta_invariants_refuse_misalignment():
    df = pd.DataFrame({"tour_atp": [0., 0.], "target": [1, 0]})
    with pytest.raises(ValueError, match="exact holdout"):
        paired_wta_holdout_diagnostics(df, np.array([.6]), np.array([.6, .4]))
    assert paired_wta_holdout_diagnostics(df, [.6, .4], None)["status"] == "NO_COMPARABLE_CHAMPION"
