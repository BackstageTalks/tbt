from datetime import datetime, timezone
from types import SimpleNamespace
import sqlite3

from tbt.data.atp_rank_history import (
    ATPRankHistory,
    ATP_RANK_HISTORY_FEATURE_NAMES,
)
from tbt.services.training import (
    PRODUCTION_FEATURE_NAMES,
    _candidate_feature_names,
)


def _match(day="2025-01-06"):
    return SimpleNamespace(
        tour="atp",
        scheduled_at=datetime.fromisoformat(day + "T12:00:00+00:00"),
        player1_name="Alpha One",
        player2_name="Beta Two",
    )


def test_same_day_ranking_snapshot_is_never_used():
    rows = [
        {"date": datetime(2024, 12, 2).date(), "rank": "20", "name": "Alpha One", "points": "1200"},
        {"date": datetime(2024, 12, 2).date(), "rank": "40", "name": "Beta Two", "points": "800"},
        {"date": datetime(2024, 12, 30).date(), "rank": "10", "name": "Alpha One", "points": "1800"},
        {"date": datetime(2024, 12, 30).date(), "rank": "30", "name": "Beta Two", "points": "1000"},
        {"date": datetime(2025, 1, 6).date(), "rank": "1", "name": "Alpha One", "points": "4000"},
        {"date": datetime(2025, 1, 6).date(), "rank": "2", "name": "Beta Two", "points": "3500"},
    ]
    history = ATPRankHistory(rows)
    features = history.features_for_match(_match())
    assert features["atp_hist_known_both"] == 1.0
    # Previous 2024-12-30 week must be used, not the same-day 2025-01-06 table.
    expected = __import__("math").log1p(30) - __import__("math").log1p(10)
    assert abs(features["atp_hist_rank_advantage"] - expected) < 1e-12


def test_sqlite_loader_and_candidate_governance(tmp_path):
    db = tmp_path / "rankings.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute('CREATE TABLE "2024-12-02" (rank TEXT, name TEXT, points TEXT)')
        conn.execute('CREATE TABLE "2024-12-30" (rank TEXT, name TEXT, points TEXT)')
        for table, values in {
            "2024-12-02": [("20", "Alpha One", "1200"), ("40", "Beta Two", "800")],
            "2024-12-30": [("10", "Alpha One", "1800"), ("30", "Beta Two", "1000")],
        }.items():
            conn.executemany(f'INSERT INTO "{table}" VALUES (?,?,?)', values)
        conn.commit()
    finally:
        conn.close()

    history = ATPRankHistory.from_sqlite(db)
    features = history.features_for_match(_match("2025-01-02"))
    assert features["atp_hist_known_both"] == 1.0
    assert features["atp_hist_points_advantage"] > 0

    assert not (set(ATP_RANK_HISTORY_FEATURE_NAMES) & set(PRODUCTION_FEATURE_NAMES))
    default_names = _candidate_feature_names()
    enabled_names = _candidate_feature_names(atp_rank_history=history)
    assert not (set(ATP_RANK_HISTORY_FEATURE_NAMES) & set(default_names))
    assert set(ATP_RANK_HISTORY_FEATURE_NAMES).issubset(enabled_names)
