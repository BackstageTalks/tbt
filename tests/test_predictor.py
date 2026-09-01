import numpy as np

from tbt.services.predictor import predict_matches


class EloOnlyModel:
    version = "test-elo"

    def predict_proba(self, frame):
        return np.asarray(frame["elo_probability"], dtype=float)


def test_prediction_probabilities_are_symmetric_and_sum_to_one(match_factory):
    history = [
        match_factory("a1", "A", "C", "A", day=1),
        match_factory("a2", "A", "D", "A", day=2),
        match_factory("b1", "B", "E", "E", day=1),
        match_factory("b2", "B", "F", "F", day=2),
    ]
    upcoming = [match_factory("u1", "A", "B", None, day=5)]
    result = predict_matches(EloOnlyModel(), history, upcoming)[0]
    assert abs(result.player1_probability + result.player2_probability - 1.0) < 1e-12
    assert result.predicted_winner_id == "A"
