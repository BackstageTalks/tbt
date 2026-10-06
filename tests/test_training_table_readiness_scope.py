from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_production_training_table import (
    READINESS_WINDOW_START_UTC,
    build_report,
)


def test_readiness_uses_modern_window_without_hiding_all_history():
    frame = pd.DataFrame(
        {
            "scheduled_at": pd.to_datetime(
                [
                    "2010-01-01T12:00:00Z",
                    "2011-01-01T12:00:00Z",
                    "2021-01-01T12:00:00Z",
                    "2022-01-01T12:00:00Z",
                ],
                utc=True,
            ),
            "stats_known_both": [0.0, 0.0, 1.0, 1.0],
            "environment_known": [0.0, 0.0, 1.0, 1.0],
            "travel_known": [0.0, 0.0, 1.0, 1.0],
            "altitude_change_known": [0.0, 0.0, 1.0, 1.0],
            "indoor_known": [0.0, 0.0, 1.0, 1.0],
            "weather_known": [0.0, 0.0, 0.0, 0.0],
            "tour": ["atp", "wta", "atp", "wta"],
            "year": ["2010", "2011", "2021", "2022"],
            "surface": ["hard", "clay", "hard", "clay"],
        }
    )

    report = build_report(
        frame,
        quality={"with_statistics": 2},
        rank_provenance={},
    )

    assert READINESS_WINDOW_START_UTC == "2021-01-01T00:00:00Z"
    assert report["coverage"]["overall"]["environment_known_rate"] == 0.5
    assert report["coverage"]["readiness_window"]["environment_known_rate"] == 1.0
    assert report["coverage"]["readiness_window"]["stats_known_both_rate"] == 1.0

    env = report["candidate_feature_groups"]["static_environment"]
    stats = report["candidate_feature_groups"]["event_statistics"]
    assert env["coverage"] == 0.5
    assert env["readiness_coverage"] == 1.0
    assert env["ready_for_candidate_eval"] is True
    assert stats["coverage"] == 0.5
    assert stats["readiness_coverage"] == 1.0
    assert stats["ready_for_candidate_eval"] is True
