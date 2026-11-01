"""Guarantee weekly MoviOdds import cannot silently skip a BUSY CDB writer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from moviodds_cdb_retry import decision, COOLDOWN_SECONDS


def utc(day: str) -> datetime:
    return datetime.fromisoformat(day.replace("Z", "+00:00"))


def runs(*items, total_count=None):
    items = list(items)
    return {"workflow_runs": items,
            "total_count": len(items) if total_count is None else total_count}


def attempt(*, status="completed", conclusion="failure",
            created="2026-11-01T06:01:00Z",
            title="CDB guarded import moviodds-2026-11-01",
            branch="main", event="workflow_dispatch"):
    return {"display_title": title, "status": status,
            "conclusion": conclusion, "head_branch": branch, "event": event,
            "created_at": created}


def test_first_weekly_slot_only_after_sunday_06_utc():
    assert decision(runs(), utc("2026-11-01T05:59:00Z"))["dispatch"] is False
    row = decision(runs(), utc("2026-11-01T06:00:00Z"))
    assert row == {"dispatch": True, "reason": "first_weekly_attempt",
                   "request_id": "moviodds-2026-11-01"}
    # Missed Sunday 06 dispatch can be safely recovered next morning.
    assert decision(runs(), utc("2026-11-02T06:00:00Z"))["request_id"] == "moviodds-2026-11-01"
    assert decision(runs(), utc("2026-11-02T06:00:00Z"))["dispatch"] is True


def test_active_queued_or_in_progress_attempt_never_duplicated():
    for status in ("queued", "in_progress", "waiting", "pending"):
        r = decision(runs(attempt(status=status, conclusion=None)),
                     utc("2026-11-01T09:00:00Z"))
        assert r["dispatch"] is False
        assert r["reason"] == "existing_attempt_active"


def test_success_is_terminal_for_the_week_and_does_not_overwrite_cdb():
    result = decision(runs(attempt(status="completed", conclusion="success")),
                      utc("2026-11-07T23:30:00Z"))
    assert result["dispatch"] is False
    assert result["reason"] == "weekly_import_verified_complete"


def test_failed_busy_attempt_not_green_and_retry_after_cooldown():
    r = runs(attempt())
    before = utc("2026-11-01T06:01:00Z") + timedelta(seconds=COOLDOWN_SECONDS - 1)
    after = before + timedelta(seconds=1)
    assert decision(r, before)["reason"] == "failed_attempt_cooldown"
    assert decision(r, after)["reason"] == "retry_failed_or_busy_attempt"
    assert decision(r, after)["dispatch"] is True


def test_previous_failure_cannot_force_duplicate_after_success():
    obj = runs(attempt(), attempt(created="2026-11-01T09:01:00Z",
                                  conclusion="success"))
    assert decision(obj, utc("2026-11-04T12:00:00Z"))["dispatch"] is False


def test_foreign_or_old_weekly_run_does_not_confirm_current_week():
    old = attempt(title="CDB guarded import moviodds-2026-10-25",
                  created="2026-10-26T06:00:00Z", conclusion="success")
    foreign = attempt(event="push", conclusion="success")
    assert decision(runs(old, foreign),
                    utc("2026-11-01T08:00:00Z"))["dispatch"] is True


def test_untrusted_or_partial_github_inventory_fails_closed():
    with pytest.raises(ValueError, match="missing workflow_runs"):
        decision({}, utc("2026-11-01T08:00:00Z"))
    with pytest.raises(ValueError, match="Incomplete"):
        decision(runs(total_count=101), utc("2026-11-01T08:00:00Z"))
    with pytest.raises(ValueError, match="timestamp"):
        decision(runs(attempt(created="2026-10-31T06:00:00Z")),
                 utc("2026-11-01T08:00:00Z"))


def test_scheduler_reuses_match_status_native_tick_without_extra_moviodds_cron():
    match_status=(ROOT/".github/workflows/match-status.yml").read_text()
    guarded=(ROOT/".github/workflows/cdb-drive-inbox.yml").read_text()
    assert "cron: '0,15,30,45 * * * *'" in match_status
    assert "\n  schedule:" not in guarded
    assert "scripts/moviodds_cdb_retry.py" in match_status
    assert "-f source_mode=moviodds -f moviodds_days_back=7" in match_status
    assert "-f created=" in match_status
    assert "MOVIODDS_CDB_DEFERRED_WRITER_BUSY_NOT_IMPORTED" in guarded
    assert "env.SOURCE_MODE == 'moviodds' && steps.source.outputs.eligible == 'true' && steps.writer_gate.outputs.ready == 'false'" in guarded
    assert "exit 1" in guarded


def test_match_status_checks_out_retry_script_and_does_not_hide_failure():
    workflow = (ROOT / ".github/workflows/match-status.yml").read_text()
    steps = workflow.split("    steps:", 1)[1]
    checkout = "      - uses: actions/checkout@v4"
    retry_step = "      - name: Dispatch or retry guarded weekly MoviOdds CDB import after Sunday 06 UTC"
    assert checkout in steps
    assert steps.index(checkout) < steps.index(retry_step)
    retry_block = steps.split(retry_step, 1)[1].split(
        "      - name: Dispatch read-only production UI revision watchdog", 1
    )[0]
    assert "continue-on-error: true" not in retry_block
    assert "python scripts/moviodds_cdb_retry.py" in retry_block
    assert "set -euo pipefail" in retry_block
    # Quality hold must prevent weekly CDB dispatch regardless of cron.
    assert "if: ${{ false }}" in retry_block
    assert "QUALITY HOLD 2026-11-01" in retry_block
    assert "0 verified CDB additions" in retry_block
    # Keep already working final source capture and research-only stage enabled.
    final_capture = steps.split("      - name: Capture finalized MoviOdds tennis statistics in DB", 1)[1].split("      - name: Dispatch completed Telegram", 1)[0]
    stage = steps.split("      - name: Dispatch autonomous MoviOdds CDB candidate preparation once daily", 1)[1].split("      - name: Archive completed MoviOdds", 1)[0]
    assert "if: ${{ false }}" not in final_capture
    assert "if: ${{ false }}" not in stage
    assert "gh workflow run moviodds-cdb-stage.yml" in stage


def test_late_global_writer_race_cannot_report_moviodds_import_success():
    workflow = (ROOT / ".github/workflows/cdb-drive-inbox.yml").read_text()
    late = workflow.split(
        "      - name: Acquire global single writer ONLY for a positive, validated delta", 1
    )[1].split(
        "      - name: Atomic CAS verification and select immutable backup years", 1
    )[0]
    assert 'if [[ "$SOURCE_MODE" == "drive" ]]; then' in late
    assert "python scripts/cdb_inbox_pending_batch.py persist" in late
    assert "MOVIODDS_CDB_DEFERRED_LATE_LOCK_RACE_NOT_IMPORTED" in late
    assert "exit 1" in late.split("MOVIODDS_CDB_DEFERRED_LATE_LOCK_RACE_NOT_IMPORTED", 1)[1]
