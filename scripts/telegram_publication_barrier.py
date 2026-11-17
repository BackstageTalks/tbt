"""Read-only final-publication barrier for BlinQ's morning Telegram delivery.

The current website generation is NOT a finality certificate while a related
production deploy is running. The barrier requires a successful deployment of
that generation and refuses active/failed newer production publications.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from urllib.request import Request, urlopen

PRODUCTION_JOBS = {
    "data.yml": "Deploy current prediction generation",
    "ci.yml": "deploy",
}
ACTIVE = {"queued", "pending", "requested", "waiting", "in_progress"}


def _stamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Deployment audit timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def assess_publication_deployment(runs_and_jobs, feed_generated_at):
    """Pure fail-closed check of recent production writer jobs and final success."""
    feed_at = _stamp(feed_generated_at)
    jobs = []
    for workflow, records in runs_and_jobs.items():
        if workflow not in PRODUCTION_JOBS or not isinstance(records, list):
            raise ValueError("Unexpected publication job audit shape")
        for item in records:
            if not isinstance(item, dict):
                raise ValueError("Invalid publishing run")
            run = item.get("run") or {}
            if run.get("head_branch") != "main":
                continue
            created = _stamp(run["created_at"])
            if created < feed_at - timedelta(hours=3):
                continue
            publishes = [
                j for j in item.get("jobs", []) or []
                if isinstance(j, dict)
                and j.get("name") == PRODUCTION_JOBS[workflow]
            ]
            if not publishes and run.get("status") in ACTIVE:
                # A queued CI deploy job may not exist in the Jobs API until
                # its checks finish. Do not treat an unfinished workflow as a
                # non-publisher merely because that job is not listed yet.
                raise RuntimeError("Final offer not ready: active workflow may still deploy")
            for job in publishes:
                status, conclusion = str(job.get("status") or ""), str(job.get("conclusion") or "")
                if status in ACTIVE:
                    raise RuntimeError("Final offer not ready: related production deployment still running")
                if status != "completed":
                    raise RuntimeError("Final offer not ready: unknown publication job status")
                if conclusion == "skipped":
                    continue
                if conclusion == "success":
                    completed = _stamp(job["completed_at"])
                    if completed >= feed_at:
                        jobs.append((created, "success", workflow, run.get("id")))
                else:
                    jobs.append((created, "failed", workflow, run.get("id")))
    jobs.sort(key=lambda r: r[0], reverse=True)
    if not jobs or jobs[0][1] != "success":
        raise RuntimeError("Final offer not ready: no successful latest production publication")
    return {"status": "final_deployment_verified",
            "workflow": jobs[0][2], "run_id": jobs[0][3],
            "feed_generated_at": feed_at.isoformat()}


def verify_live_publication_barrier(source, *, token, repository, now=None,
                                    activation_day="2026-11-18", reader=None):
    """Use the existing GitHub Actions read API; no provider requests or writes."""
    from telegram_offer_publisher import day
    now = now or datetime.now(timezone.utc)
    if day(now) < activation_day:
        return {"status": "legacy_day"}
    if (not token or not re.fullmatch(r"[\w.-]+/[\w.-]+", str(repository or ""))
            or not isinstance(source, dict)
            or not source.get("source_feed_generated_at")):
        raise RuntimeError("Final deployment verification requires trusted source and Actions credentials")

    def api(path):
        if reader is not None:
            return reader(path)
        request = Request("https://api.github.com/repos/" + repository + "/" + path,
                          headers={"Authorization": "Bearer " + token,
                                   "Accept": "application/vnd.github+json",
                                   "X-GitHub-Api-Version": "2022-11-28"})
        with urlopen(request, timeout=15) as response:
            blob = response.read(500001)
        if len(blob) > 500000:
            raise RuntimeError("Publishing workflow verification response exceeds limit")
        return json.loads(blob)

    data = {}
    for workflow in PRODUCTION_JOBS:
        value = api("actions/workflows/" + workflow + "/runs?per_page=30")
        records = value.get("workflow_runs")
        if not isinstance(records, list):
            raise RuntimeError("Final deployment verification missing workflow history")
        matched = []
        feed_at = _stamp(source["source_feed_generated_at"])
        for run in records:
            if not isinstance(run, dict) or run.get("head_branch") != "main":
                continue
            if _stamp(run["created_at"]) < feed_at - timedelta(hours=3):
                continue
            if len(matched) >= 15:
                raise RuntimeError("Too many concurrent publication runs for bounded finality check")
            job_response = api("actions/runs/" + str(int(run["id"])) + "/jobs?per_page=100")
            if not isinstance(job_response.get("jobs"), list):
                raise RuntimeError("Final deployment verification missing job history")
            matched.append({"run": run, "jobs": job_response["jobs"]})
        data[workflow] = matched
    return assess_publication_deployment(data, source["source_feed_generated_at"])
