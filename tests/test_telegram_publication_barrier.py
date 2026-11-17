"""Ranný TG sa nesmie odoslať pred dokončením relevantného deploymentu."""
from datetime import datetime, timezone

import pytest

from telegram_publication_barrier import (
    assess_publication_deployment, verify_live_publication_barrier,
)

GENERATED = "2026-11-17T05:01:00.000201+00:00"


def run(id_, created="2026-11-17T05:19:33Z", status="in_progress"):
    return {"id": id_, "created_at": created, "head_branch": "main", "status": status}


def job(status="in_progress", conclusion=None, completed=None,
        name="Deploy current prediction generation"):
    return {"name": name, "status": status, "conclusion": conclusion,
            "completed_at": completed}


def data_state(*jobs, created="2026-11-17T05:19:33Z", status="in_progress", run_id=44023302604):
    return {"data.yml": [{"run": run(run_id, created, status), "jobs": list(jobs)}],
            "ci.yml": []}


def test_actual_incident_reproduced_deploy_in_progress_while_tg_sends():
    # 05:20:56 preflight 5 TOP, 05:21 TG 3 TOP, 05:22:36 live web 5 TOP.
    state = data_state(job(status="in_progress"))
    with pytest.raises(RuntimeError, match="still running"):
        assess_publication_deployment(state, GENERATED)


def test_successful_latest_deploy_is_required_before_daily_tg():
    state = data_state(job(status="completed", conclusion="success",
                           completed="2026-11-17T05:23:24Z"),
                       status="completed")
    assert assess_publication_deployment(state, GENERATED) == {
        "status": "final_deployment_verified",
        "workflow": "data.yml", "run_id": 44023302604,
        "feed_generated_at": "2026-11-17T05:01:00.000201+00:00",
    }


def test_failed_newer_deploy_is_not_hidden_by_older_success():
    data = data_state(job(status="completed", conclusion="success",
                          completed="2026-11-17T05:23:24Z"),
                      status="completed")
    data["data.yml"].insert(0, {"run": run(9, "2026-11-17T05:25:00Z", "completed"),
                                   "jobs": [job(status="completed", conclusion="failure",
                                                completed="2026-11-17T05:26:00Z")]})
    with pytest.raises(RuntimeError, match="no successful latest"):
        assess_publication_deployment(data, GENERATED)


def test_no_completed_publish_refuses_to_treat_http_200_as_finality():
    with pytest.raises(RuntimeError, match="no successful latest"):
        assess_publication_deployment({"data.yml": [], "ci.yml": []}, GENERATED)


def test_queued_or_waiting_publish_blocks_even_after_earlier_success():
    data = data_state(job(status="completed", conclusion="success",
                          completed="2026-11-17T05:23:24Z"), status="completed")
    data["ci.yml"] = [{
        "run": run(5, "2026-11-17T05:24:00Z", "in_progress"),
        "jobs": [job(status="queued", name="deploy")],
    }]
    with pytest.raises(RuntimeError, match="still running"):
        assess_publication_deployment(data, GENERATED)


def test_ci_checks_in_progress_without_deploy_job_is_not_final():
    data = data_state(job(status="completed", conclusion="success",
                          completed="2026-11-17T05:23:24Z"), status="completed")
    data["ci.yml"] = [{"run": run(8, "2026-11-17T05:24:00Z", "in_progress"),
                       "jobs": [{"name": "checks", "status": "in_progress"}]}]
    with pytest.raises(RuntimeError, match="active workflow may still deploy"):
        assess_publication_deployment(data, GENERATED)


def test_nonpublishing_skipped_workflow_does_not_overrule_success():
    data = data_state(job(status="completed", conclusion="success",
                          completed="2026-11-17T05:23:24Z"), status="completed")
    data["data.yml"].insert(0, {
        "run": run(6, "2026-11-17T05:28:00Z", "completed"),
        "jobs": [job(status="completed", conclusion="skipped")],
    })
    assert assess_publication_deployment(data, GENERATED)["run_id"] == 44023302604


def test_live_gate_reads_github_actions_without_paid_provider_calls():
    now = datetime(2026, 11, 18, 5, 25, tzinfo=timezone.utc)
    stamp = "2026-11-18T05:01:00Z"
    entries = {
        "actions/workflows/data.yml/runs?per_page=30": {"workflow_runs": [
            run(17, "2026-11-18T05:20:00Z", "completed")]},
        "actions/runs/17/jobs?per_page=100": {"jobs": [
            job(status="completed", conclusion="success",
                completed="2026-11-18T05:23:00Z")]},
        "actions/workflows/ci.yml/runs?per_page=30": {"workflow_runs": []},
    }
    calls = []
    def reader(path):
        calls.append(path)
        return entries[path]
    out = verify_live_publication_barrier(
        {"source_feed_generated_at": stamp},
        token="test-only", repository="BackstageTalks/tbt", now=now,
        reader=reader,
    )
    assert out["status"] == "final_deployment_verified"
    assert len(calls) == 3


def test_live_gate_refuses_unknown_credentials_and_does_not_regrade_legacy():
    now = datetime(2026, 11, 18, 5, 25, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match="requires trusted"):
        verify_live_publication_barrier({"source_feed_generated_at": GENERATED},
                                        token="", repository="BackstageTalks/tbt", now=now)
    old = datetime(2026, 11, 17, 5, 25, tzinfo=timezone.utc)
    assert verify_live_publication_barrier({}, token=None, repository=None,
                                           now=old)["status"] == "legacy_day"
