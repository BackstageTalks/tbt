from __future__ import annotations

import pandas as pd

from audit_rank_history_ablation import chronological_partitions


def test_rank_history_partitions_are_disjoint_and_future_only():
    frame = pd.DataFrame({
        "match_id": ["a", "b", "c", "d"],
        "scheduled_at": [
            "2026-06-30T12:00:00Z",
            "2026-07-15T12:00:00Z",
            "2026-09-26T12:00:00Z",
            "2026-10-01T12:00:00Z",
        ],
        "target": [1, 0, 1, 0],
    })
    train, calibration, test = chronological_partitions(
        frame, pd.Timestamp("2026-09-25T20:46:00Z")
    )
    assert train["match_id"].tolist() == ["a"]
    assert calibration["match_id"].tolist() == ["b"]
    assert test["match_id"].tolist() == ["c", "d"]
    assert not (set(train.match_id) & set(calibration.match_id))
    assert not (set(train.match_id) & set(test.match_id))
