"""One read-only command for protected training; never a promotion gate."""
import argparse
import json
import subprocess

REPO = "BackstageTalks/tbt"
LOCK = "repos/BackstageTalks/tbt-data/git/ref/tags/blinq-cdb-global-writer"


def get(path):
    result = subprocess.run(["gh", "api", "--method", "GET", path],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Cannot read {path}; state is unverified")
    return json.loads(result.stdout)


def snapshot(run_id=None, read=get):
    if run_id is None:
        runs = read(f"repos/{REPO}/actions/workflows/protected-frozen-cdb-candidate.yml/runs?per_page=1")["workflow_runs"]
        if not runs:
            raise RuntimeError("No protected training run found")
        run_id = runs[0]["id"]
    run = read(f"repos/{REPO}/actions/runs/{run_id}")
    attempt = run["run_attempt"]
    jobs = read(f"repos/{REPO}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
    if jobs["total_count"] != len(jobs["jobs"]):
        raise RuntimeError("Incomplete job list; state is unverified")
    active, failed, passed = [], [], []
    for job in jobs["jobs"]:
        for step in job.get("steps", []):
            if step.get("status") == "in_progress":
                active.append(step["name"])
            if step.get("conclusion") in {"failure", "cancelled", "timed_out"}:
                failed.append(step["name"])
            if step.get("conclusion") == "success":
                passed.append(step["name"])
    lock = "UNVERIFIED"
    try:
        ref = read(LOCK)
        sha = ref["object"]["sha"]
        tag = read(f"repos/BackstageTalks/tbt-data/git/tags/{sha}")
        again = read(LOCK)
        expected = f"owner={REPO}/actions/runs/{run_id}/attempts/{attempt}"
        if again["object"]["sha"] == sha and tag["sha"] == sha:
            lock = "OWNED_BY_THIS_RUN" if tag["message"].strip() == expected else "OTHER_OWNER"
    except (RuntimeError, KeyError, TypeError):
        # A 404 may also mean inaccessible private data. Never claim free.
        pass
    state = "EXECUTING" if run["status"] != "completed" else (
        "WORKFLOW_SUCCEEDED" if run["conclusion"] == "success" else "BLOCKED")
    return {"state": state, "run_id": run_id, "attempt": attempt,
            "commit": run["head_sha"], "url": run["html_url"],
            "active_steps": active, "failed_steps": failed,
            "last_successful_step": passed[-1] if passed else None,
            "lock": lock, "release_readiness": "NOT_VERIFIED",
            "remaining_release_checks": "Independent artifact readback, champion and 7.1.1 comparison, ATP/WTA stability and calibration, real pre-match TOP odds >= 1.50 with sample size, hit rate, ROI and uncertainty"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=int, help="Default: newest protected training run")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = snapshot(args.run)
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        parser.exit(2, f"UNVERIFIED: {exc}\n")
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['state']} | run {result['run_id']} / attempt {result['attempt']} | {result['commit'][:12]}")
        print("Step: " + (", ".join(result['failed_steps'] or result['active_steps']) or "No active step"))
        print(f"Lock: {result['lock']} | Release: {result['release_readiness']}")
        print(result['url'])
    return 1 if result["state"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
