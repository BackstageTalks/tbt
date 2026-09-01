from tbt.models.metrics import evaluate_probabilities


def test_good_probabilities_beat_coin_flip():
    y = [1, 1, 0, 0, 1, 0]
    good = [0.85, 0.75, 0.2, 0.1, 0.7, 0.35]
    coin = [0.5] * len(y)
    assert evaluate_probabilities(y, good)["log_loss"] < evaluate_probabilities(y, coin)["log_loss"]
    assert evaluate_probabilities(y, good)["brier_score"] < evaluate_probabilities(y, coin)["brier_score"]
