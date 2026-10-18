#!/usr/bin/env python3
"""One-shot, fail-closed operator recovery of one confirmed abandoned CDB writer lock.

This is intentionally NOT a general stale-lock sweeper. Never expire a live owner.
Unowned lock recovery requires terminal GitHub run and terminal job checks.
The follow-on importer must acquire a NEW lock normally; no lock is transferred.
"""
import json
import os
import subprocess

DATA_REPO = "BackstageTalks/tbt-data"
OWNER_REPO = "BackstageTalks/tbt"
FAILED_RUN = 39115897871
FAILED_ATTEMPT = 1
ABANDONED_SHA = "723b20fc33916708bf8a79303caa08953ddb9dc0"
OWNER = f"{OWNER_REPO}/actions/runs/{FAILED_RUN}/attempts/{FAILED_ATTEMPT}"
REF = "git/ref/tags/blinq-cdb-global-writer"
DELETE_REF = "git/refs/tags/blinq-cdb-global-writer"

def gh_api(path, method="GET"):
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("No authenticated GH_TOKEN; fail closed.")
    cmd = ["gh", "api", "--method", method, path]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError("GitHub " + method + " failed: " + out.stderr[-450:])
    return json.loads(out.stdout) if out.stdout.strip() else {}

def current_ref(api=gh_api):
    try:
        return api(f"repos/{DATA_REPO}/{REF}")
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise

def recover(api=gh_api):
    remote = current_ref(api)
    if remote is None:
        return "no_lock"
    actual = remote.get("object", {}).get("sha")
    if actual != ABANDONED_SHA:
        return "different_owner_intact"
    run = api(f"repos/{OWNER_REPO}/actions/runs/{FAILED_RUN}")
    if not (
        run.get("status") == "completed"
        and run.get("conclusion") == "failure"
        and run.get("run_attempt") == FAILED_ATTEMPT
        and run.get("id") == FAILED_RUN
    ):
        raise RuntimeError("Refusing stale-lock cleanup: original owner is not provably terminal.")
    jobs = api(f"repos/{OWNER_REPO}/actions/runs/{FAILED_RUN}/jobs?per_page=100")
    all_jobs = jobs.get("jobs", [])
    if (not all_jobs or jobs.get("total_count", 0) != len(all_jobs)
            or any(job.get("status") != "completed" for job in all_jobs)):
        raise RuntimeError("Refusing stale-lock cleanup: owning jobs not all terminal.")
    tag = api(f"repos/{DATA_REPO}/git/tags/{ABANDONED_SHA}")
    if tag.get("message") != f"owner={OWNER}" or tag.get("object", {}).get("type") != "commit":
        raise RuntimeError("Refusing stale-lock cleanup: annotated tag owner mismatch.")
    again = current_ref(api)
    if again is None or again.get("object", {}).get("sha") != ABANDONED_SHA:
        raise RuntimeError("Lock moved during recovery; no deletion.")
    api(f"repos/{DATA_REPO}/{DELETE_REF}", method="DELETE")
    return "recovered_single_confirmed_abandoned_lock"

if __name__ == "__main__":
    result = recover()
    print("CDB abandoned-lock safety check:", result, flush=True)
