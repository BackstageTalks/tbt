"""Network-free post-reset quota window regression tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.api_hourly_evening import evening_cap


def reset_window(day):
    reset = datetime.fromisoformat(day + "T17:09:00+00:00")
    return reset, reset + timedelta(days=1)


@pytest.mark.parametrize("day", ["2026-01-12", "2026-07-12"])
def test_provider_reset_utc_independent_of_bratislava_dst(day):
    previous, upcoming = reset_window(day)
    assert evening_cap(previous + timedelta(minutes=44), upcoming) is None
    assert evening_cap(previous + timedelta(minutes=45), upcoming) == 3000
    assert evening_cap(previous + timedelta(hours=1, minutes=54), upcoming) == 4200
    assert evening_cap(previous + timedelta(hours=3, minutes=54), upcoming) == 6600
    assert evening_cap(previous + timedelta(hours=5, minutes=54), upcoming) == 8500
    assert evening_cap(previous + timedelta(hours=6), upcoming) is None


def test_evening_policy_cannot_exhaust_shared_quota_before_morning():
    _, upcoming = reset_window("2026-11-03")
    from_reset = upcoming - timedelta(days=1)
    for minutes in range(45, 360):
        cap = evening_cap(from_reset + timedelta(minutes=minutes), upcoming)
        assert 3000 <= cap <= 8500
        assert 14500 - cap >= 6000


def test_fail_closed_on_naive_timestamps():
    before, after = reset_window("2026-11-03")
    with pytest.raises(ValueError, match="timezone-aware"):
        evening_cap(before.replace(tzinfo=None), after)
    with pytest.raises(ValueError, match="timezone-aware"):
        evening_cap(before, after.replace(tzinfo=None))


def test_workflow_preserves_quota_guards_and_disables_overnight_targeted_dispatch():
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/data-hourly-quota-gapfill.yml").read_text()
    assert "evening_limit" not in workflow
    assert "new_day_start" not in workflow
    assert workflow.count("daytime_slot = stage_hour in caps and until_reset <= 9 * 3600") == 2
    assert workflow.count("limit = 14500 if final_topup else caps[stage_hour]") == 2
    assert "from scripts.api_writer_wait import read_cdb_writer_lock" in workflow
    assert "from scripts.api_writer_wait import wait_for_writer" in workflow
    assert "or budget.get(\"global_limit\") != 14500" in workflow
    assert "or budget.get(\"reserved_provider_headroom\") != 500" in workflow
    assert workflow.count("proposed = min(5000,") == 2
    assert "Less than 15 minutes until provider cutoff" in workflow
