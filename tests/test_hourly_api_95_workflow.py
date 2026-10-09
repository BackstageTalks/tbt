"""Contract regression for the operator-triggered 95% provider-day stats fill."""
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


def test_95_percent_shared_budget_and_provider_headroom():
    assert shared_budget.PROVIDER_PLAN_LIMIT == 15000
    assert shared_budget.PROVIDER_RESERVE == 750
    assert shared_budget.GLOBAL_CEILING == 14250
    assert shared_budget.PURPOSE_CAPS["history"] == 14250
    assert DEFAULT_PROVIDER_REQUEST_RESERVE == 750
    assert 'budget.get("global_limit") != 14250' in HOURLY
    assert 'budget.get("reserved_provider_headroom") != 750' in HOURLY
    assert 'remaining != max(0, 14250-spent)' in HOURLY
    assert 'caps = {hour: 14250 for hour in range(12, 19)}' in HOURLY


def test_1850_final_start_and_provider_reset_are_bounded():
    assert "18:50" in HOURLY
    assert "local.hour == 18 and local.minute > 57" in HOURLY
    assert "time(19, 5)" in HOURLY
    assert "cutoff - timedelta(minutes=8)" in HOURLY
    assert "reset.astimezone(ZONE).minute != 10" in HOURLY
    assert '"autofill_stop_at_utc": cutoff.isoformat()' in HOURLY
    assert 'BLINQ_API_AUTOFILL_STOP_AT_UTC' in DATA


def test_writer_and_two_independent_quota_guards():
    assert 'group: tbt-hourly-api-gapfill-orchestrator' in HOURLY
    assert 'if active:' in HOURLY
    assert 'check_writers()' in HOURLY
    assert 'min(3000, limit-spent, remaining, history_remaining)' in HOURLY
    assert 'group: tbt-history-data-writer' in DATA
    assert 'BLINQ_PROVIDER_REQUEST_RESERVE=750' in DATA
    assert 'BLINQ_RAPIDAPI_MAX_RPS=6' in DATA
    assert '"hourly_autofill": "true"' in HOURLY
    assert 'BLINQ_REQUIRE_PROVIDER_RATE_LIMIT_HEADER' in DATA
    assert 'inputs.mode == \'refresh\'' in DATA  # no automatic model promotion
