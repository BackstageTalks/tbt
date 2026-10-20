"""Regression tests for safe hourly API writer contention retries."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.api_writer_wait import wait_for_writer


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/data-hourly-quota-gapfill.yml").read_text(encoding="utf-8")


def test_busy_writer_retries_until_it_frees_without_any_dispatch_or_lock_write():
    now = [datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)]
    states = [["data.yml run=1 status=in_progress"],
              ["data.yml run=1 status=in_progress"], []]
    sleeps = []

    def check():
        return states.pop(0)

    def pause(seconds):
        sleeps.append(seconds)
        now[0] += timedelta(seconds=seconds)

    waited = wait_for_writer(
        check, now[0] + timedelta(minutes=3),
        clock=lambda: now[0], pause=pause,
    )
    assert waited is True
    assert sleeps == [45, 45]
    assert states == []


def test_free_writer_does_not_wait():
    sleeps = []
    now = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
    assert wait_for_writer(lambda: [], now + timedelta(minutes=2),
                           clock=lambda: now, pause=sleeps.append) is False
    assert sleeps == []


def test_busy_writer_expires_loudly_and_never_executes_api_requests():
    now = [datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)]
    sleeps = []
    checks = []

    def check():
        checks.append("read_only")
        return ["data.yml run=1 status=in_progress"]

    def pause(seconds):
        sleeps.append(seconds)
        now[0] += timedelta(seconds=seconds)

    with pytest.raises(TimeoutError, match="retry window expired"):
        wait_for_writer(check, now[0] + timedelta(seconds=60),
                        clock=lambda: now[0], pause=pause)
    assert sleeps == [45, 15]
    assert len(checks) == 3


def test_unknown_writer_state_fails_closed():
    def inaccessible_writer_state():
        raise RuntimeError("GitHub status API unavailable")

    now = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match="unavailable"):
        wait_for_writer(inaccessible_writer_state, now + timedelta(minutes=1),
                        clock=lambda: now, pause=lambda _: None)


def test_hourly_workflow_rechecks_budget_and_keeps_quota_and_writer_guards():
    # Workflow must load repository files before importing scripts.api_writer_wait.
    checkout = WORKFLOW.index("      - uses: actions/checkout@v4")
    importer = WORKFLOW.index("from scripts.api_writer_wait import wait_for_writer")
    assert checkout < importer
    assert "timeout-minutes: 350" in WORKFLOW
    assert "wait_for_writer(check_writers, retry_deadline)" in WORKFLOW
    assert "now + timedelta(hours=5, minutes=40)" in WORKFLOW
    assert "time(19, 3)" in WORKFLOW
    assert "if waited:" in WORKFLOW
    delayed = WORKFLOW.split("          if waited:", 1)[1]
    assert "budget_response = get_json(BUDGET_URL, WORKER, worker=True)" in delayed
    assert 'budget.get("provider_plan_limit") != 15000' in delayed
    assert 'budget.get("global_limit") != 14500' in delayed
    assert 'budget.get("reserved_provider_headroom") != 500' in delayed
    assert "remaining != max(0, 14500-spent)" in delayed
    assert "reset.astimezone(ZONE).minute != 10" in delayed
    assert "limit = 3000 if new_day_start else (14500 if final_topup else caps[local.hour])" in delayed
    assert "min(3000, limit-spent, remaining, history_remaining)" in delayed
    assert "if proposed < 1:" in delayed
    assert '"hourly_autofill": "true"' in delayed
    # Lock acquisition remains with the existing governed data.yml pipeline.
    assert "git/refs" not in delayed
    assert "git/tags" not in delayed
