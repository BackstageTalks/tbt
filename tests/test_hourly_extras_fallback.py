"""Network-free regression tests for verified same-writer RapidAPI recovery."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.hourly_extras_fallback import plan


RUN_ID = "43902745969"
NOW = datetime(2026, 11, 16, 15, 16, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 11, 16, 17, 7, tzinfo=timezone.utc)


def verified(*, paid=215, gained=52, reason="cross_tour_paid_statistics_unavailable"):
    sample = 24 if reason == "verified_prior_zero_gain_cross_tour_recheck" else 120
    download = {
        "requests_including_retries": paid,
        "statistics_availability_circuit": {
            "tripped": True,
            "trigger": {
                "reason": reason,
                "scope": "current_high_yield_statistics_run_only",
                "recent_paid_matches": sample,
                "recent_paid_attempts": sample,
                "recent_unavailable_matches": sample,
                "recent_new_canonical_fields": 0,
                "sampled_cohorts": 3,
                "sampled_tours": 2,
            },
        },
    }
    readback = {"status": "VERIFIED" if gained else "VERIFIED_NO_NEW_FIELDS",
                "persisted_new_statistic_values": gained}
    evidence = {
        "status": "VERIFIED_CDB_GAIN" if gained else "VERIFIED_NO_GAIN",
        "run_id": RUN_ID,
        "requests_including_retries": paid,
        "persisted_new_statistic_values": gained,
    }
    return download, readback, evidence


def select(data=None, *, max_calls=4515, now=NOW, cutoff=CUTOFF, run_id=RUN_ID):
    return plan(*(data or verified()), original_limit=max_calls,
                run_id=run_id, cutoff=cutoff, now=now)


def test_recovers_only_residual_allowance_after_verified_circuit():
    outcome = select()
    assert outcome["status"] == "ELIGIBLE"
    assert outcome["reason"] == "verified_statistics_unavailable"
    assert outcome["max_requests"] == 4515 - 215
    assert outcome["statistics_paid_requests"] == 215
    assert outcome["evidence"] == "same_run_remote_CDB_readback_and_paid_cross_tour_circuit"


def test_verified_prior_short_cross_tour_recheck_is_eligible():
    assert select(verified(paid=24, gained=0,
                           reason="verified_prior_zero_gain_cross_tour_recheck"))[
                               "max_requests"] == 4491


@pytest.mark.parametrize("mutate,reason", [
    (lambda d, r, e: d.pop("statistics_availability_circuit"),
     "statistics_route_not_stopped_by_availability_circuit"),
    (lambda d, r, e: d["statistics_availability_circuit"].update(tripped=False),
     "statistics_route_not_stopped_by_availability_circuit"),
    (lambda d, r, e: d["statistics_availability_circuit"]["trigger"].update(
        reason="another_error"), "insufficient_cross_tour_paid_unavailability_evidence"),
    (lambda d, r, e: d["statistics_availability_circuit"]["trigger"].update(
        sampled_tours=1), "insufficient_cross_tour_paid_unavailability_evidence"),
    (lambda d, r, e: d["statistics_availability_circuit"]["trigger"].update(
        recent_unavailable_matches=100),
     "insufficient_cross_tour_paid_unavailability_evidence"),
    (lambda d, r, e: d["statistics_availability_circuit"]["trigger"].update(
        recent_new_canonical_fields=1),
     "insufficient_cross_tour_paid_unavailability_evidence"),
    (lambda d, r, e: r.update(status="UNVERIFIED"),
     "statistics_remote_readback_not_verified"),
    (lambda d, r, e: e.update(run_id="other"),
     "statistics_remote_readback_not_verified"),
    (lambda d, r, e: e.update(requests_including_retries=216),
     "inconsistent_verified_metrics"),
    (lambda d, r, e: e.update(persisted_new_statistic_values=51),
     "inconsistent_verified_metrics"),
    (lambda d, r, e: d.update(requests_including_retries=5001),
     "inconsistent_verified_metrics"),
    (lambda d, r, e: d.update(requests_including_retries=True),
     "inconsistent_verified_metrics"),
])
def test_does_not_spend_on_invalid_circuit_or_cdb_evidence(mutate, reason):
    data = verified()
    mutate(*data)
    result = select(data)
    assert result["allowed"] is False
    assert result["max_requests"] == 0
    assert result["reason"] == reason


def test_terminated_statistics_without_unused_calls_never_runs_extras():
    result = select(verified(paid=4515))
    assert result["reason"] == "original_run_allowance_exhausted"
    assert result["max_requests"] == 0


@pytest.mark.parametrize("max_calls", [0, 5001, 14500, True, -5])
def test_rejects_unbounded_or_invalid_per_run_maximum(max_calls):
    assert select(max_calls=max_calls)["reason"] == "invalid_hourly_run_allowance"


@pytest.mark.parametrize("now", [
    datetime(2026, 11, 16, 16, 55, tzinfo=timezone.utc),
    datetime(2026, 11, 16, 17, 8, tzinfo=timezone.utc),
    datetime(2026, 11, 16, 17, 9, tzinfo=timezone.utc),
])
def test_rejects_late_dispatch_and_provider_reset(now):
    result = select(now=now)
    assert not result["allowed"]
    assert result["max_requests"] == 0


def test_rejects_stale_or_naive_utc_cutoff():
    assert select(cutoff=CUTOFF - timedelta(days=1))["reason"] == (
        "cutoff_not_current_provider_day"
    )
    assert select(cutoff=CUTOFF.replace(tzinfo=None))["reason"] == (
        "untrusted_provider_time"
    )


def test_workflow_preserves_lock_and_sequential_readback_before_fallback():
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/data.yml").read_text()
    stats_verify = workflow.index(
        "name: Independently verify every targeted CDB statistics publication")
    stats_summary = workflow.index(
        "name: Summarize independently verified adaptive hourly CDB value")
    fallback_plan = workflow.index(
        "name: Plan verified same-writer extras fallback after statistics circuit")
    fallback_import = workflow.index(
        "name: Continue provider-native extras under same CDB writer and allowance")
    extras_verify = workflow.index(
        "name: Independently verify every event extras CDB publication")
    lock_release = workflow.index("name: Release cross-repository canonical writer")
    assert stats_verify < stats_summary < fallback_plan < fallback_import < extras_verify < lock_release
    assert "python scripts/hourly_extras_fallback.py" in workflow
    assert "steps.verified_extras_fallback.outputs.allowed == 'true'" in workflow
    assert 'BLINQ_AUTOFILL_HIGH_YIELD=false python scripts/download_tennis_history.py' in workflow
    assert 'FALLBACK_MAX_REQUESTS <= 5000' in workflow
    assert '"$BLINQ_API_AUTOFILL_STOP_AT_UTC"' in workflow
    assert "BLINQ_PROVIDER_REQUEST_RESERVE: '500'" in workflow
    assert "BLINQ_RAPIDAPI_MAX_RPS=6" in workflow
    assert "hourly_extras_fallback_plan.json" in workflow


def test_external_cron_and_orchestrator_contract_are_unchanged():
    root = Path(__file__).resolve().parents[1]
    hourly = (root / ".github/workflows/data-hourly-quota-gapfill.yml").read_text()
    assert "group: tbt-hourly-api-gapfill-orchestrator" in hourly
    assert 'or budget.get("global_limit") != 14500' in hourly
    assert 'or budget.get("reserved_provider_headroom") != 500' in hourly
    assert "from scripts.api_writer_wait import read_cdb_writer_lock" in hourly
    assert "from scripts.api_writer_wait import wait_for_writer" in hourly
    assert "BLINQ_NATIVE_SCHEDULES_ENABLED == 'true'" in hourly
