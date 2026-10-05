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
