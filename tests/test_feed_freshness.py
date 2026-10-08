"""Regression guards for the daily serving snapshot's 06:00 Bratislava boundary."""
from datetime import datetime

from tbt.services.feed import visible_feed


def _stale(generated_at, now):
    stamp = datetime.fromisoformat(now.replace("Z", "+00:00"))
    return visible_feed({"generated_at": generated_at, "upcoming": [], "results": []}, now=stamp)["stale"]


def test_morning_feed_remains_fresh_during_evening():
    # 04:10Z = 06:10 Europe/Bratislava in October.
    assert _stale("2026-10-08T04:10:47Z", "2026-10-08T17:52:00Z") is False


def test_morning_feed_goes_stale_at_next_betting_day():
    assert _stale("2026-10-08T04:10:47Z", "2026-10-09T03:59:00Z") is False
    assert _stale("2026-10-08T04:10:47Z", "2026-10-09T04:01:00Z") is True


def test_just_before_morning_boundary_is_previous_day():
    assert _stale("2026-10-08T03:59:00Z", "2026-10-08T04:01:00Z") is True


def test_winter_betting_day_uses_cet_offset():
    assert _stale("2026-12-01T05:05:00Z", "2026-12-01T22:59:00Z") is False
    assert _stale("2026-12-01T05:05:00Z", "2026-12-02T05:01:00Z") is True


def test_missing_or_implausibly_future_dated_feed_is_stale():
    assert _stale(None, "2026-10-08T12:00:00Z") is True
    assert _stale("2026-10-08T14:00:00Z", "2026-10-08T12:00:00Z") is True
