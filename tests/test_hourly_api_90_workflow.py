"""UTC-anchored shared TennisAPI quota and staged hourly closeout contracts."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tbt.providers import shared_budget
from tbt.providers.rapidapi import DEFAULT_PROVIDER_REQUEST_RESERVE


ROOT = Path(__file__).resolve().parents[1]
HOURLY = (ROOT / ".github/workflows/data-hourly-quota-gapfill.yml").read_text(encoding="utf-8")
DATA = (ROOT / ".github/workflows/data.yml").read_text(encoding="utf-8")


def test_real_manual_trigger_not_dry_run_by_default():
    assert "workflow_dispatch:" in HOURLY
    assert "default: false" in HOURLY
    assert "gh workflow run" not in HOURLY
    assert '"mode": "statistics"' in HOURLY
    assert '"promote": "false"' in HOURLY


def test_14700_shared_budget_and_guarded_provider_headroom():
    assert shared_budget.PROVIDER_PLAN_LIMIT == 15000
    assert shared_budget.PROVIDER_RESERVE == 300
    assert shared_budget.GLOBAL_CEILING == 14700
    assert shared_budget.PURPOSE_CAPS["history"] == 14700
    assert DEFAULT_PROVIDER_REQUEST_RESERVE == 300
    assert 'budget.get("global_limit") != 14700' in HOURLY
    assert 'budget.get("reserved_provider_headroom") != 300' in HOURLY
    assert 'remaining != max(0, 14700-spent)' in HOURLY
    assert 'budget.get("schema") != 2' in HOURLY
    assert '"provider_day_17_09_utc"' in HOURLY
    assert 'limit = 3000 if new_day_start else (14700 if final_topup else caps[stage_hour])' in HOURLY


def test_hourly_writer_and_dual_quota_guards():
    assert 'group: tbt-hourly-api-gapfill-orchestrator' in HOURLY
    assert 'if active:' in HOURLY
    assert 'check_writers()' in HOURLY
    assert 'min(3000, limit-spent, remaining, history_remaining)' in HOURLY
    assert 'group: tbt-crossrepo-writer-${{ github.run_id }}' in DATA
    assert 'BLINQ_PROVIDER_REQUEST_RESERVE=300' in DATA
    assert 'BLINQ_RAPIDAPI_MAX_RPS=6' in DATA
    assert '"hourly_autofill": "true"' in HOURLY
    assert 'BLINQ_REQUIRE_PROVIDER_RATE_LIMIT_HEADER' in DATA
    assert 'inputs.mode == \'refresh\'' in DATA
    assert '"autofill_stop_at_utc": cutoff.isoformat()' in HOURLY
    assert 'cutoff = expected_reset - timedelta(minutes=2)' in HOURLY


def test_utc_closeout_window_and_restart_season_independent():
    # Exercise the pure workflow time-policy itself, not a duplicate algorithm.
    lines = HOURLY.splitlines()
    function_start = next(i for i, x in enumerate(lines) if x.strip() == "def next_provider_reset(instant):")
    function_body = "\n".join(x[10:] for x in lines[function_start:function_start + 5])
    closeout_line = next(x.strip() for x in lines if x.strip().startswith("final_topup = "))
    fresh_line = next(x.strip() for x in lines if x.strip().startswith("new_day_start = "))
    namespace = {"timedelta": timedelta}
    exec(function_body, namespace)
    next_reset = namespace["next_provider_reset"]
    for day in ((2026, 9, 27), (2026, 10, 25)):
        day_start = datetime(*day, 17, 9, tzinfo=timezone.utc)
        for mins_before, expected in ((36, False), (35, True), (7, True), (6, False)):
            now = day_start - timedelta(minutes=mins_before)
            until_reset = (next_reset(now) - now).total_seconds()
            scope = {"until_reset": until_reset, "now": now}
            exec(closeout_line + "\n" + fresh_line, {}, scope)
            assert scope["final_topup"] is expected
            assert not scope["new_day_start"]
        for mins_after in (1, 2, 3, 4, 5):
            now = day_start + timedelta(minutes=mins_after)
            scope = {"until_reset": (next_reset(now) - now).total_seconds(), "now": now}
            exec(closeout_line + "\n" + fresh_line, {}, scope)
            assert not scope["final_topup"]
            assert scope["new_day_start"] is (mins_after <= 4)
