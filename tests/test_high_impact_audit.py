import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_high_impact import calibration_buckets, coverage


def test_selected_side_calibration_covers_boundaries_and_underdogs():
    bins = calibration_buckets([.5, .55, .6, .65, .7, .8, 1., 0., .2], [1, 0, 1, 0, 1, 1, 1, 0, 1])
    assert sum(item["n"] for item in bins) == 9
    assert bins[0]["n"] == 1
    assert bins[-1]["n"] == 4
    assert bins[-1]["actual_win_rate"] == .75


def test_zero_difference_is_not_missing_when_availability_flag_is_observed():
    result = coverage(pd.DataFrame({"serve_quality_diff": [0., 0.], "stats_known_both": [1., 0.]}))
    assert result["availability"]["stats_known_both"]["observed_rows"] == 1
    assert "serve_quality_diff" not in result["availability"]
