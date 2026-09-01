from tbt.services.contracts import blinq_flat_prediction, public_prediction


def sample_row():
    return {
        "match_id": "x1",
        "scheduled_at": "2026-09-01T12:00:00Z",
        "tour": "atp",
        "tournament": "Test Open",
        "surface": "hard",
        "round_name": "R16",
        "player1_id": "1",
        "player1_name": "Player A",
        "player1_rank": 10,
        "player2_id": "2",
        "player2_name": "Player B",
        "player2_rank": 20,
        "player1_probability": 0.64,
        "player2_probability": 0.36,
        "predicted_winner_id": "1",
        "predicted_winner_name": "Player A",
        "confidence_pct": 64.0,
        "confidence_band": "medium",
        "signals": [],
        "model_version": "v200-test",
    }


def test_public_contract_probabilities_are_consistent():
    payload = public_prediction(sample_row())
    assert payload["player1"]["win_probability_pct"] == 64.0
    assert payload["player2"]["win_probability_pct"] == 36.0
    assert payload["prediction"]["winner_name"] == "Player A"


def test_blinq_flat_contract_has_stable_keys():
    payload = blinq_flat_prediction(sample_row())
    required = {"id", "date", "p1", "p2", "p1_prob", "p2_prob", "pick", "probability", "model"}
    assert required <= set(payload)
