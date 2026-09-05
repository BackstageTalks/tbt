from tbt.models.metrics import evaluate_probabilities


def test_good_probabilities_beat_coin_flip():
    y = [1, 1, 0, 0, 1, 0]
    good = [0.85, 0.75, 0.2, 0.1, 0.7, 0.35]
    coin = [0.5] * len(y)
    assert evaluate_probabilities(y, good)["log_loss"] < evaluate_probabilities(y, coin)["log_loss"]
    assert evaluate_probabilities(y, good)["brier_score"] < evaluate_probabilities(y, coin)["brier_score"]
from tbt.models.metrics import selective_accuracy


def test_selective_accuracy_reports_coverage_and_empty_thresholds():
    rows = selective_accuracy([1, 0, 0, 1], [.8, .2, .6, .55])
    assert rows[0]["n"] == 4
    assert rows[0]["accuracy"] == .75
    row = next(r for r in rows if r["threshold"] == .75)
    assert row["n"] == 2 and row["coverage"] == .5 and row["accuracy"] == 1
    assert rows[-1]["accuracy"] is None
