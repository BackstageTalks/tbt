from datetime import datetime, timedelta, timezone

import pytest

from scripts.morning_clock import (
    morning_publication_at,
    morning_publication_delay,
    morning_selection_now,
)


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        # 05:15 CET -> 06:01 CET (winter).
        (datetime(2026, 1, 15, 4, 15, tzinfo=timezone.utc),
         datetime(2026, 1, 15, 5, 1, tzinfo=timezone.utc)),
        # 05:15 CEST -> 06:01 CEST (summer).
        (datetime(2026, 9, 28, 3, 15, tzinfo=timezone.utc),
         datetime(2026, 9, 28, 4, 1, tzinfo=timezone.utc)),
        # First Sunday of CET -> CEST (already 05:15 CEST).
        (datetime(2026, 3, 29, 3, 15, tzinfo=timezone.utc),
         datetime(2026, 3, 29, 4, 1, tzinfo=timezone.utc)),
        # First Sunday of CEST -> CET (05:15 CET).
        (datetime(2026, 10, 25, 4, 15, tzinfo=timezone.utc),
         datetime(2026, 10, 25, 5, 1, tzinfo=timezone.utc)),
    ],
)
def test_before_six_targets_same_local_calendar_day(start, expected):
    assert morning_publication_at(start) == expected
    assert morning_selection_now(start) == expected
    assert morning_publication_delay(start) == 46 * 60


def test_completion_after_six_never_waits_or_uses_earlier_clock():
    now = datetime(2026, 9, 28, 4, 35, tzinfo=timezone.utc)
    assert morning_selection_now(now) == now
    assert morning_publication_delay(now) == 0


def test_exact_0601_is_immediately_eligible():
    now = datetime(2026, 9, 28, 4, 1, tzinfo=timezone.utc)
    assert morning_selection_now(now) == now
    assert morning_publication_delay(now) == 0


def test_midnight_and_naive_timestamp_are_fail_closed():
    now = datetime(2026, 9, 28, 0, 30, tzinfo=timezone.utc)
    assert morning_publication_at(now) == datetime(
        2026, 9, 28, 4, 1, tzinfo=timezone.utc
    )
    with pytest.raises(ValueError):
        morning_selection_now(datetime(2026, 9, 28, 5, 15))
    with pytest.raises(ValueError):
        morning_publication_delay(now, start_hour=24)
