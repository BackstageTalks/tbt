"""Network-free post-reset quota window regression tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.api_hourly_evening import evening_cap, hourly_wait_window_open, completed_history_end


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


@pytest.mark.parametrize("date", ["2026-01-13", "2026-07-13"])
def test_queued_gapfill_waits_for_safe_dispatch_slot_across_utc_reset(date):
    def at(hhmm):
        return datetime.fromisoformat(date + "T" + hhmm + ":00+00:00")

    assert hourly_wait_window_open(at("16:51")) is True
    assert hourly_wait_window_open(at("16:52")) is False
    assert hourly_wait_window_open(at("17:08")) is False
    assert hourly_wait_window_open(at("17:10")) is True
    assert hourly_wait_window_open(at("17:13")) is True
    assert hourly_wait_window_open(at("17:14")) is False
    assert hourly_wait_window_open(at("17:54")) is True
    assert hourly_wait_window_open(at("23:09")) is False


def test_wait_window_rejects_unknown_timezone():
    with pytest.raises(ValueError, match="timezone-aware"):
        hourly_wait_window_open(datetime(2026, 11, 13, 16, 51))


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

def test_external_clock_reuses_only_guarded_capacity_windows():
    from scripts.api_hourly_evening import external_clock_gapfill_decision

    def check(iso, wanted, reason=None):
        now = datetime.fromisoformat(iso)
        allowed, why, _ = external_clock_gapfill_decision(now, [])
        assert allowed is wanted, (iso, why)
        if reason is not None:
            assert why == reason

    check("2026-11-11T08:49:00+00:00", False, "outside_existing_guarded_slots")
    check("2026-11-11T10:00:00+00:00", True)  # winter 11:00 CET
    check("2026-07-11T10:00:00+00:00", True)  # summer 12:00 CEST
    check("2026-07-11T09:00:00+00:00", False)
    check("2026-11-11T16:36:00+00:00", True)  # final closeout
    check("2026-11-11T16:50:00+00:00", False, "provider_cutoff_preflight")
    check("2026-11-11T18:00:00+00:00", True)  # after reset, evening cap
    check("2026-11-11T04:00:00+00:00", False)


def test_external_clock_prevents_duplicate_and_active_writer_orchestrator():
    from scripts.api_hourly_evening import external_clock_gapfill_decision

    now = datetime(2026, 11, 11, 10, 30, tzinfo=timezone.utc)

    def run(at, status, conclusion=None, event="workflow_dispatch"):
        return {
            "created_at": at.isoformat().replace("+00:00", "Z"),
            "status": status, "conclusion": conclusion, "event": event,
        }

    assert external_clock_gapfill_decision(
        now, [run(now - timedelta(minutes=40), "in_progress")])[1] == "orchestrator_already_active"
    assert external_clock_gapfill_decision(
        now, [run(now - timedelta(minutes=20), "completed", "success")])[1] == "already_dispatched_this_slot"
    assert external_clock_gapfill_decision(
        now, [run(now - timedelta(minutes=8), "completed", "failure")])[1] == "retry_cooldown"
    assert external_clock_gapfill_decision(
        now, [run(now - timedelta(minutes=18), "completed", "failure")])[0] is True
    assert external_clock_gapfill_decision(
        now, [run(now - timedelta(minutes=18), "completed", "failure"),
              run(now - timedelta(minutes=28), "completed", "failure")])[1] == (
                  "repeated_guard_failures_need_diagnosis"
              )
    assert external_clock_gapfill_decision(
        now, [run(now - timedelta(minutes=20), "completed", "success", event="schedule")])[0] is True
    assert external_clock_gapfill_decision(
        now, [run(now - timedelta(hours=7), "in_progress")])[0] is True

    # Closeout is a separate allowance even after a successful 16:00 UTC
    # staged run; it must still stop with >=500 provider headroom.
    closeout = datetime(2026, 11, 11, 16, 36, tzinfo=timezone.utc)
    assert external_clock_gapfill_decision(
        closeout, [run(closeout.replace(minute=10), "completed", "success")])[0] is True
    assert external_clock_gapfill_decision(
        closeout, [run(closeout.replace(minute=34), "completed", "success")])[1] == "already_dispatched_this_slot"


def test_external_clock_invalid_metadata_fails_closed():
    from scripts.api_hourly_evening import external_clock_gapfill_decision

    now = datetime(2026, 11, 11, 10, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="timezone-aware"):
        external_clock_gapfill_decision(now.replace(tzinfo=None), [])
    with pytest.raises(ValueError, match="Ambiguous"):
        external_clock_gapfill_decision(now, [
            {"event": "workflow_dispatch", "created_at": "2026-11-11T09:00:00"}
        ])
    with pytest.raises(ValueError, match="Future"):
        external_clock_gapfill_decision(now, [{
            "event": "workflow_dispatch", "created_at": "2026-11-11T11:00:00Z"
        }])


def test_external_cron_handoff_uses_only_existing_protected_orchestrator():
    source = (Path(__file__).resolve().parents[1] /
              ".github/workflows/match-status.yml").read_text()
    assert source.count("name: Dispatch guarded CDB API gapfill from existing external clock") == 1
    assert "if: always() && github.event_name == 'workflow_dispatch'" in source
    assert "gh workflow run data-hourly-quota-gapfill.yml" in source
    assert "from scripts.api_hourly_evening import external_clock_gapfill_decision" in source
    assert "CDB_API_GAPFILL_ORCHESTRATOR_DISPATCH_VERIFIED" in source
    assert 'jq -e \u0027.total_count <= 100' in source
    assert "continue-on-error: true\n        env:\n          GH_TOKEN:" not in source.split(
        "- name: Dispatch guarded CDB API gapfill from existing external clock", 1)[1]
    # No new GitHub native cron or direct CDB import/writer in the handoff.
    assert "cron: '0,15,30,45 * * * *'" in source
    tail = source.split(
        "- name: Dispatch guarded CDB API gapfill from existing external clock", 1)[1]
    assert "download_tennis_history.py" not in tail
    assert "cdb_global_writer_lock.py" not in tail

@pytest.mark.parametrize("instant,expected", [
    ("2026-11-12T23:02:00+00:00", "2026-11-11"),
    ("2026-07-12T22:02:00+00:00", "2026-07-11"),
    ("2026-11-13T00:02:00+00:00", "2026-11-12"),
    ("2026-07-13T00:02:00+00:00", "2026-07-12"),
    ("2026-11-13T16:30:00+00:00", "2026-11-12"),
    ("2026-07-13T16:30:00+00:00", "2026-07-12"),
])
def test_history_end_is_complete_in_both_utc_and_local_day(instant, expected):
    from datetime import date
    observed = completed_history_end(datetime.fromisoformat(instant))
    assert observed == date.fromisoformat(expected)
    assert observed < datetime.fromisoformat(instant).astimezone(timezone.utc).date()


def test_history_end_fails_closed_for_naive_clock_and_workflow_uses_helper():
    with pytest.raises(ValueError, match="aware dispatch"):
        completed_history_end(datetime(2026, 11, 12, 23, 2))
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/data-hourly-quota-gapfill.yml").read_text()
    assert "last_complete = completed_history_end(now)" in workflow
    assert "last_complete = local.date() - timedelta(days=1)" not in workflow
    assert "from scripts.api_hourly_evening import (evening_cap" in workflow
    assert "hourly_wait_window_open, completed_history_end)" in workflow
    assert '\"end\": last_complete.isoformat()' in workflow

