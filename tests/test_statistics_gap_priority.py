from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from download_tennis_history import _statistics_candidates


def _match(mid, tour, when, stats):
    return SimpleNamespace(
        match_id=mid,
        tour=tour,
        scheduled_at=datetime.fromisoformat(when).replace(tzinfo=timezone.utc),
        stats=stats,
        is_completed=True,
    )


def _full():
    return {
        "p1_service_points_won": 0.62,
        "p1_return_points_won": 0.38,
        "p2_service_points_won": 0.61,
        "p2_return_points_won": 0.39,
    }


def test_statistics_candidates_skip_ready_and_prioritize_low_coverage_bucket():
    rows = [
        _match("wta-partial", "WTA", "2022-06-02T12:00:00", {
            "p1_service_points_won": 0.62,
            "p1_return_points_won": 0.38,
        }),
        _match("wta-empty", "WTA", "2022-06-03T12:00:00", {}),
        _match("wta-empty-2", "WTA", "2022-06-04T12:00:00", {}),
        _match("atp-ready", "ATP", "2025-06-01T12:00:00", _full()),
        _match("atp-gap", "ATP", "2025-06-02T12:00:00", {}),
    ]

    candidates, report = _statistics_candidates(
        rows, date(2022, 1, 1), date(2025, 12, 31)
    )

    assert [row.match_id for row in candidates] == [
        "wta-partial",
        "wta-empty-2",
        "wta-empty",
        "atp-gap",
    ]
    assert "atp-ready" not in [row.match_id for row in candidates]
    assert report["candidate_rows"] == 4
    assert report["already_quality_ready"] == 1
    assert report["bucket_coverage"]["wta:2022"]["quality_ready_rate"] == 0.0
    assert report["bucket_coverage"]["atp:2025"]["quality_ready_rate"] == 0.5


def test_statistics_candidates_respect_requested_window():
    rows = [
        _match("old-gap", "WTA", "2021-12-31T12:00:00", {}),
        _match("in-gap", "WTA", "2022-01-01T12:00:00", {}),
        _match("future-gap", "WTA", "2026-01-01T12:00:00", {}),
    ]
    candidates, report = _statistics_candidates(
        rows, date(2022, 1, 1), date(2025, 12, 31)
    )
    assert [row.match_id for row in candidates] == ["in-gap"]
    assert report["window_completed"] == 1
