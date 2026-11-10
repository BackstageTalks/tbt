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


def test_workflow_preserves_existing_guards_and_uses_evening_in_both_paths():
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/data-hourly-quota-gapfill.yml").read_text()
    assert workflow.count("evening_limit = evening_cap(now, expected_reset)") == 2
    assert workflow.count("if evening_limit is not None:") == 2
    assert workflow.count("limit = evening_limit") == 2
    assert workflow.count("limit = 3000 if new_day_start else (14500 if final_topup else caps[stage_hour])") == 2
    assert "from scripts.api_writer_wait import read_cdb_writer_lock" in workflow
    assert "from scripts.api_writer_wait import wait_for_writer" in workflow
    assert "or budget.get(\"global_limit\") != 14500" in workflow
    assert "or budget.get(\"reserved_provider_headroom\") != 500" in workflow
    assert workflow.count("proposed = min(5000,") == 2
    assert "Less than 15 minutes until provider cutoff" in workflow


def test_operator_one_off_500_smoke_is_fresh_and_only_restrictive(tmp_path):
    import json
    from scripts.api_hourly_evening import operator_smoke_request_cap

    now = datetime(2026, 11, 10, 17, 15, tzinfo=timezone.utc)
    tick = tmp_path / "tick.json"
    request = {
        "schema": 1, "source": "operator-approved-500-statistics-smoke",
        "max_requests": 500, "requested_utc": "2026-11-10T17:10:00Z",
    }
    tick.write_text(json.dumps(request))
    assert operator_smoke_request_cap(tick, enabled=True, now=now) == 500
    assert operator_smoke_request_cap(tick, enabled=False, now=now) is None
    for invalid in [0, 501, True, "500"]:
        tick.write_text(json.dumps({**request, "max_requests": invalid}))
        with pytest.raises(ValueError, match="Invalid operator smoke request cap"):
            operator_smoke_request_cap(tick, enabled=True, now=now)

    tick.write_text(json.dumps(request))
    with pytest.raises(ValueError, match="expired"):
        operator_smoke_request_cap(tick, enabled=True,
                                   now=now + timedelta(minutes=26))
    tick.write_text(json.dumps({**request, "requested_utc": "2026-11-10T17:16:00Z"}))
    with pytest.raises(ValueError, match="expired"):
        operator_smoke_request_cap(tick, enabled=True, now=now)


def test_workflow_operator_smoke_cap_never_increases_proposed_allowance():
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/data-hourly-quota-gapfill.yml").read_text()
    assert workflow.count("tick_cap = operator_smoke_request_cap(") == 2
    assert workflow.count("proposed = min(proposed, tick_cap)") == 2
    assert "TICK_500_SMOKE:" in workflow
    assert workflow.count("0 <= since_reset < 45 * 60") == 2
    assert workflow.count("evening_limit = 3000") == 2
