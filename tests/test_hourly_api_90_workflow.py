"""UTC-anchored shared TennisAPI quota and staged hourly closeout contracts."""
from datetime import datetime, timedelta, timezone
import ast
import re
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


def test_14500_shared_budget_and_guarded_provider_headroom():
    assert shared_budget.PROVIDER_PLAN_LIMIT == 15000
    assert shared_budget.PROVIDER_RESERVE == 500
    assert shared_budget.GLOBAL_CEILING == 14500
    assert shared_budget.PURPOSE_CAPS["history"] == 14500
    assert DEFAULT_PROVIDER_REQUEST_RESERVE == 500
    assert 'budget.get("global_limit") != 14500' in HOURLY
    assert 'budget.get("reserved_provider_headroom") != 500' in HOURLY
    assert 'remaining != max(0, 14500-spent)' in HOURLY
    assert 'budget.get("schema") != 2' in HOURLY
    assert '"provider_day_17_09_utc"' in HOURLY
    assert 'limit = 14500 if final_topup else caps[stage_hour]' in HOURLY



def test_daytime_from_11_bratislava_and_two_stage_ceilings():
    match = re.search(r"caps = (\\{[^}]+\\})", HOURLY)
    assert match is not None
    caps = ast.literal_eval(match.group(1))
    assert set(caps) == set(range(11, 19))
    assert caps[11] == 5700
    assert caps[17] == caps[18] == 13500
    assert max(caps.values()) == 13500
    assert HOURLY.count("stage_hour = local.hour") == 2
    assert HOURLY.count("daytime_slot = stage_hour in caps and until_reset <= 9 * 3600") == 2
    assert HOURLY.count("limit = 14500 if final_topup else caps[stage_hour]") == 2
    assert "new_day_start" not in HOURLY and "evening_limit" not in HOURLY
    assert "14800" not in HOURLY and "14700" not in HOURLY
    assert "14,800" not in HOURLY and "14,700" not in HOURLY

def test_hourly_writer_and_dual_quota_guards():
    assert 'group: tbt-hourly-api-gapfill-orchestrator' in HOURLY
    assert 'if active:' in HOURLY
    assert 'check_writers()' in HOURLY
    assert 'min(5000, limit-spent, remaining, history_remaining)' in HOURLY
    assert 'min(5000, limit-spent, 14500-spent, remaining, history_remaining)' in HOURLY
    assert '(( 10#$MAX_REQUESTS <= 5000 ))' in DATA
    assert 'Hourly autofill cap is 5000' in DATA
    assert 'group: tbt-crossrepo-writer-${{ github.run_id }}' in DATA
    assert 'BLINQ_PROVIDER_REQUEST_RESERVE=500' in DATA
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
    namespace = {"timedelta": timedelta}
    exec(function_body, namespace)
    next_reset = namespace["next_provider_reset"]
    for day in ((2026, 9, 27), (2026, 10, 25)):
        day_start = datetime(*day, 17, 9, tzinfo=timezone.utc)
        for mins_before, expected in ((36, False), (35, True), (7, True), (6, False)):
            now = day_start - timedelta(minutes=mins_before)
            until_reset = (next_reset(now) - now).total_seconds()
            scope = {"until_reset": until_reset, "now": now}
            exec(closeout_line, {}, scope)
            assert scope["final_topup"] is expected
        for mins_after in (1, 2, 3, 4, 5):
            now = day_start + timedelta(minutes=mins_after)
            scope = {"until_reset": (next_reset(now) - now).total_seconds(), "now": now}
            exec(closeout_line, {}, scope)
            assert not scope["final_topup"]

def test_refresh_pipeline_and_standing_contract_use_shared_14500_ceiling():
    # Prevent the workflow accepting 14,500 while the inner parser rejects it.
    pipeline = (ROOT / "scripts/pipeline.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--max-requests", type=int, default=14500)' in pipeline
    assert 'if not 1 <= args.max_requests <= 14500:' in pipeline
    assert 'parser.error("refresh allowance must be 1..14500")' in pipeline
    assert "14700" not in pipeline
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "**14,500 global BlinQ ceiling**" in agents
    assert "**500 reserved**" in agents
    assert "**17:09 UTC**" in agents
    assert "**14,550 global BlinQ ceiling**" not in agents

