from tbt.services.prime import prime_components, prime_diagnostics, prime_score_from_components


def _row(probability=0.75, depth=0.8, elo=0.25):
    return {
        "player1_id": "a",
        "player2_id": "b",
        "predicted_winner_id": "a",
        "player1_probability": probability,
        "player2_probability": 1.0 - probability,
        "features": {
            "elo_diff": elo,
            "surface_elo_diff": 0.20,
            "rank_advantage": 0.8,
            "recent_form_diff": 0.12,
            "opponent_adjusted_form_diff": 0.08,
            "surface_form_diff": 0.10,
            "h2h_advantage": 0.20,
            "rest_advantage": 0.10,
            "layoff_advantage": 0.0,
            "fatigue_3d_advantage": 0.05,
            "fatigue_7d_advantage": 0.02,
            "data_depth": depth,
        },
    }


def test_probability_strength_is_zero_at_coin_flip():
    components = prime_components(_row(probability=0.5))
    assert components["model_probability_strength"] == 0.0


def test_stronger_probability_increases_score_with_probability_only_weight():
    weights = {"model_probability": 1.0, "data_depth": 0.0, "factor_agreement": 0.0}
    low = prime_diagnostics(_row(probability=0.60), weights=weights)["score"]
    high = prime_diagnostics(_row(probability=0.80), weights=weights)["score"]
    assert high > low


def test_score_is_ranking_value_not_probability_copy():
    diag = prime_diagnostics(_row(probability=0.75))
    assert 0.0 <= diag["score"] <= 100.0
    assert diag["winner_probability_pct"] == 75.0
    assert diag["score"] != diag["winner_probability_pct"]


def test_custom_weights_are_normalized():
    components = prime_components(_row())
    score_a = prime_score_from_components(
        components,
        {"model_probability": 7, "data_depth": 2, "factor_agreement": 1},
    )
    score_b = prime_score_from_components(
        components,
        {"model_probability": 0.7, "data_depth": 0.2, "factor_agreement": 0.1},
    )
    assert abs(score_a - score_b) < 1e-12
