from datetime import datetime, timedelta, timezone

import numpy as np

from tbt.schemas import MatchRecord
from tbt.services.training import train_from_matches
from tbt.models.symmetry import swap_frame


def test_end_to_end_training_reports_real_match_counts_and_symmetric_outputs():
    rng = np.random.default_rng(24)
    matches = []
    for i in range(1200):
        a, b = rng.choice(24, 2, replace=False)
        p = 1 / (1 + np.exp(-(a - b) / 12))
        matches.append(MatchRecord(
            match_id=str(i), tour="atp", scheduled_at=datetime(2023, 1, 1, tzinfo=timezone.utc) + timedelta(days=i // 4),
            player1_id=str(a), player2_id=str(b), player1_name=str(a), player2_name=str(b),
            winner_id=str(a if rng.random() < p else b), surface="hard",
        ))
    result = train_from_matches(matches, min_matches=1000)
    report = result.report
    assert sum(report["data"][k] for k in ("train", "calibration", "holdout")) == 1200
    assert report["holdout"]["selective_accuracy"][0]["n"] == report["data"]["holdout"]
    frame = result.feature_frame.tail(20)
    assert np.allclose(result.model.predict_proba(frame) + result.model.predict_proba(swap_frame(frame)), 1)
