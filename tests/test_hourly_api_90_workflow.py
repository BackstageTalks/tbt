"""Contract regression for staged 90% and guarded 97% provider-day closeout."""
from pathlib import Path

from tbt.providers import shared_budget
from tbt.providers.rapidapi import DEFAULT_PROVIDER_REQUEST_RESERVE


ROOT = Path(__file__).resolve().parents[1]
HOURLY = (ROOT / ".github/workflows/data-hourly-quota-gapfill.yml").read_text(encoding="utf-8")
DATA = (ROOT / ".github/workflows/data.yml").read_text(encoding="utf-8")


def test_real_manual_trigger_not_dry_run_by_default():
    assert "workflow_dispatch:" in HOURLY
    assert "default: false" in HOURLY
    assert "gh workflow run" not in HOURLY  # GitHub dispatch is authenticated directly
    assert '"mode": "statistics"' in HOURLY
    assert '"promote": "false"' in HOURLY


def test_97_percent_shared_budget_and_provider_headroom():
    assert shared_budget.PROVIDER_PLAN_LIMIT == 15000
    assert shared_budget.PROVIDER_RESERVE == 450
    assert shared_budget.GLOBAL_CEILING == 14550
    assert shared_budget.PURPOSE_CAPS["history"] == 14550
    assert DEFAULT_PROVIDER_REQUEST_RESERVE == 450
    assert 'budget.get("global_limit") != 14550' in HOURLY
    assert 'budget.get("reserved_provider_headroom") != 450' in HOURLY
    assert 'remaining != max(0, 14550-spent)' in HOURLY
    assert 'caps = {12: 5700, 13: 6900, 14: 8100, 15: 9300,' in HOURLY
    assert '16: 10500, 17: 12000, 18: 13500}' in HOURLY


def test_delayed_closeout_window_and_new_day_reset_are_bounded():
    assert "18:45" in HOURLY
    assert "18 * 60 + 50 <= minute_of_day <= 19 * 60 + 3" in HOURLY
    assert "local.hour == 19 and not (final_topup or new_day_start)" in HOURLY
    assert "local.hour == 19 and local.minute == 11" in HOURLY
    assert "limit = 3000 if new_day_start else (14550 if final_topup else caps[local.hour])" in HOURLY
    assert "expected_reset_date = local.date() + timedelta(days=1) if new_day_start else local.date()" in HOURLY
    assert "time(19, 8)" in HOURLY
    assert "cutoff_date = local.date() + timedelta(days=1) if new_day_start else local.date()" in HOURLY
    assert "cutoff - timedelta(minutes=4)" in HOURLY
    assert "reset.astimezone(ZONE).minute != 10" in HOURLY
    assert '"autofill_stop_at_utc": cutoff.isoformat()' in HOURLY
    assert 'BLINQ_API_AUTOFILL_STOP_AT_UTC' in DATA


def test_writer_and_two_independent_quota_guards():
    assert 'group: tbt-hourly-api-gapfill-orchestrator' in HOURLY
    assert 'if active:' in HOURLY
    assert 'check_writers()' in HOURLY
    assert 'min(3000, limit-spent, remaining, history_remaining)' in HOURLY
    assert 'group: tbt-crossrepo-writer-${{ github.run_id }}' in DATA
    assert 'BLINQ_PROVIDER_REQUEST_RESERVE=450' in DATA
    assert 'BLINQ_RAPIDAPI_MAX_RPS=6' in DATA
    assert '"hourly_autofill": "true"' in HOURLY
    assert 'BLINQ_REQUIRE_PROVIDER_RATE_LIMIT_HEADER' in DATA
    assert 'inputs.mode == \'refresh\'' in DATA  # no automatic model promotion


def test_closeout_window_at_actual_runner_start_including_delay():
    from types import SimpleNamespace

    # Execute just the two pure time-policy assignments from the workflow;
    # no credentials, network, or GitHub dispatch occurs in this test.
    lines = HOURLY.splitlines()
    minute_assignment = next(line.strip() for line in lines
                             if line.strip().startswith("minute_of_day = "))
    closeout_assignment = next(line.strip() for line in lines
                               if line.strip().startswith("final_topup = "))
    for hour, minute, expected in [
        (18, 45, False), (18, 49, False), (18, 50, True),
        (18, 55, True), (18, 57, True), (18, 59, True),
        (19, 0, True), (19, 3, True), (19, 4, False),
        (19, 8, False), (19, 10, False), (19, 11, False),
    ]:
        scope = {"local": SimpleNamespace(hour=hour, minute=minute)}
        exec(minute_assignment + "\n" + closeout_assignment, {}, scope)
        assert scope["final_topup"] is expected, (hour, minute)
