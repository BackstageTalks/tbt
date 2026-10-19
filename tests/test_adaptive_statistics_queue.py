"""No-provider regression coverage for the guarded adaptive statistics queue."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from adaptive_statistics_queue import AdaptiveStatisticsQueue


def _match(mid, tour="ATP", year=2025, *, ready=False):
    stats = (
        {"p1_service_points_won": 0.6, "p1_return_points_won": 0.4,
         "p2_service_points_won": 0.62, "p2_return_points_won": 0.38}
        if ready else {"p1_service_points_won": 0.6}
    )
    return SimpleNamespace(
        match_id=mid, tour=tour,
        scheduled_at=datetime(year, 6, 1, tzinfo=timezone.utc),
        stats=stats, is_completed=True,
    )


def _gain(values=0, quality=0, ace=0):
    return {"new_statistic_values": values,
            "new_quality_ready_rows": quality,
            "new_ace_df_values": ace}


def test_zero_spend_and_cache_gains_preserve_original_queue():
    rows = [_match(f"atp-{i}") if i % 2 == 0 else
            _match(f"wta-{i}", "WTA", 2026) for i in range(110)]
    queue = AdaptiveStatisticsQueue(rows)
    actual = []
    for row in queue:
        actual.append(row.match_id)
        queue.record(row, 0, _gain(8, 1, 4))
    assert actual == [row.match_id for row in rows]
    evidence = queue.summary()
    assert evidence["observed_paid_requests"] == 0
    assert evidence["online_adaptation_used"] is False
    assert evidence["adaptive_choices"] == 0
    assert evidence["remaining_rows"] == 0


def test_online_yield_moves_quota_away_from_zero_gain_cohort():
    # The deterministic legacy baseline alternates both cohorts. Paid
    # evidence, not the match year alone, must change subsequent selection.
    rows = []
    for i in range(160):
        rows.extend((_match(f"atp-{i}"), _match(f"wta-{i}", "WTA", 2026)))
    queue = AdaptiveStatisticsQueue(
        rows, {"atp:2025": {"quality_ready_rate": 0.81},
               "wta:2026": {"quality_ready_rate": 0.30}})
    seen = []
    for row in queue:
        seen.append(row.tour.lower())
        if row.tour.lower() == "atp":
            queue.record(row, 1, _gain(12, 1, 4))
        else:
            queue.record(row, 1, _gain())
    assert len(seen) == len(rows)
    assert len({row.match_id for row in rows}) == len(rows)
    # The adaptive phase exploits ATP yield, but some WTA is still sampled.
    assert seen[100:220].count("atp") >= 85
    assert seen[100:220].count("wta") >= 10
    assert set(seen) == {"atp", "wta"}
    evidence = queue.summary()
    assert evidence["observed_paid_requests"] == 320
    assert evidence["adaptive_choices"] > 0
    assert evidence["online_adaptation_used"] is True
    assert evidence["cohorts"]["wta:2026:serve_return"]["new_statistic_values"] == 0
    assert evidence["cohorts"]["atp:2025:serve_return"]["new_quality_ready_rows"] == 160
    assert evidence["baseline_choices"] >= 80


def test_feedback_uses_pre_call_missing_field_family():
    row = _match("changed", ready=False)
    queue = AdaptiveStatisticsQueue([row])
    selected = next(queue)
    selected.stats.update({
        "p1_return_points_won": 0.4, "p2_service_points_won": 0.61,
        "p2_return_points_won": 0.39})
    queue.record(selected, 1, _gain(3, 1))
    with pytest.raises(StopIteration):
        next(queue)
    assert queue.summary()["cohorts"]["atp:2025:serve_return"]["new_quality_ready_rows"] == 1


def test_ace_only_and_serve_return_gaps_are_distinct_cohorts():
    rows = [_match("serve"), _match("ace", ready=True)]
    queue = AdaptiveStatisticsQueue(rows)
    for row in queue:
        queue.record(row, 1, _gain(4))
    assert set(queue.summary()["cohorts"]) == {
        "atp:2025:serve_return", "atp:2025:ace_df"}


def test_nonselected_feedback_and_duplicate_queue_rows_fail_closed():
    row = _match("unique")
    with pytest.raises(ValueError, match="Duplicate statistics queue object"):
        AdaptiveStatisticsQueue([row, row])
    queue = AdaptiveStatisticsQueue([row])
    with pytest.raises(ValueError, match="does not match"):
        queue.record(row, 1, _gain(4))
    next(queue)
    with pytest.raises(ValueError, match="Negative"):
        queue.record(row, -1, _gain())
