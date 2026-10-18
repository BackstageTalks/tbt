"""Read-only queue gate for a long-running frozen-CDB model training job.

This gate never creates, steals, deletes, or renews the global CDB writer lock.
The training job must *still* acquire the lock atomically after this gate.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from typing import Callable

APP_REPO = "BackstageTalks/tbt"
DATA_REPO = "BackstageTalks/tbt-data"
LOCK = f"repos/{DATA_REPO}/git/ref/tags/blinq-cdb-global-writer"
OWNER_RE = re.compile(r"^owner=(BackstageTalks/(?:tbt|tbt-data))/actions/runs/(\d+)/attempts/(\d+)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class GateBlocked(RuntimeError):
    """Cannot independently confirm a safe read-only waiting condition."""


def gh_get(path: str, *, lock_missing_ok: bool = False) -> dict | None:
    if not os.environ.get("GH_TOKEN"):
        raise GateBlocked("Authenticated GH_TOKEN is required for read-only private writer checks")
    proc = subprocess.run(["gh", "api", "--method", "GET", path],
                          text=True, capture_output=True, check=False)
    if proc.returncode:
        if lock_missing_ok and path == LOCK and re.search(r"HTTP 404\b", proc.stderr):
            return None
        raise GateBlocked("GitHub read failed; not treating API failure as an unlocked CDB")
    try:
        result = json.loads(proc.stdout)
    except (ValueError, TypeError) as exc:
        raise GateBlocked("Unparseable GitHub lock metadata") from exc
    if not isinstance(result, dict):
        raise GateBlocked("Unexpected GitHub lock metadata")
    return result


def snapshot(get: Callable[..., dict | None] = gh_get) -> str:
    """Return FREE or BUSY. A confirmed terminated lock owner is a hard failure."""
    first = get(LOCK, lock_missing_ok=True)
    if first is None:
        # Observations are not a writer lease; real acquire remains atomic later.
        second = get(LOCK, lock_missing_ok=True)
        return "FREE" if second is None else "BUSY"
    sha = (first.get("object") or {}).get("sha")
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise GateBlocked("Malformed global CDB writer ref")
    tag = get(f"repos/{DATA_REPO}/git/tags/{sha}")
    if tag is None or tag.get("sha") != sha:
        raise GateBlocked("CDB tag object mismatch")
    owner = OWNER_RE.fullmatch(str(tag.get("message", "")).strip())
    if not owner:
        raise GateBlocked("Unrecognized global writer owner")
    owner_repo, run_id, attempt = owner.groups()
    run = get(f"repos/{owner_repo}/actions/runs/{run_id}")
    if run is None or str(run.get("id")) != run_id or str(run.get("run_attempt")) != attempt:
        raise GateBlocked("Writer owner run/attempt cannot be independently verified")
    status = run.get("status")
    if status not in {"in_progress", "queued", "pending", "waiting", "requested", "completed"}:
        raise GateBlocked("Unrecognized writer lifecycle status")
    # Re-read to ensure no owner change during the liveness inspection.
    second = get(LOCK, lock_missing_ok=True)
    if second is None or (second.get("object") or {}).get("sha") != sha:
        return "BUSY"
    if status == "completed":
        jobs = get(f"repos/{owner_repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
        items = jobs.get("jobs") if isinstance(jobs, dict) else None
        if not isinstance(items, list) or not items or jobs.get("total_count", len(items)) > len(items):
            raise GateBlocked("Cannot prove every writer job has terminated")
        if any(j.get("status") != "completed" for j in items):
            return "BUSY"
        raise GateBlocked(f"Writer owner run {run_id} finished but lock remains; manual owner-scoped recovery required")
    return "BUSY"


def wait(max_seconds: int, interval_seconds: int,
         inspect: Callable[[], str] = snapshot,
         clock: Callable[[], float] = time.monotonic,
         sleep: Callable[[float], None] = time.sleep) -> None:
    if max_seconds < 0 or interval_seconds < 1:
        raise ValueError("Invalid waiting window")
    deadline = clock() + max_seconds
    while True:
        state = inspect()
        if state == "FREE":
            print("CDB writer read-only idle observation verified; atomic acquisition remains required", flush=True)
            return
        if state != "BUSY":
            raise GateBlocked("Unrecognized CDB writer read-only result")
        if clock() >= deadline:
            raise GateBlocked("CDB writer remained busy through bounded preflight window")
        sleep(min(interval_seconds, max(1, deadline - clock())))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-seconds", type=int, default=13200)
    parser.add_argument("--interval-seconds", type=int, default=30)
    args = parser.parse_args()
    wait(args.max_seconds, args.interval_seconds)


if __name__ == "__main__":
    main()
