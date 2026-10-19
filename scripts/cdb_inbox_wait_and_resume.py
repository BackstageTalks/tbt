"""Durable, read-only CDB writer queue gate with bounded runner leases.

A live cross-repository writer must never cause the inbox job to fail simply
because it takes a long time. Poll the verified existing lock and, before the
runner lease expires, schedule a fresh workflow_dispatch. GitHub dispatch
events from GITHUB_TOKEN are permitted; downstream writes still require a new
atomic writer acquisition, manifest CAS and remote readback.

A stale/invalid writer lock, auth failure or queue-dispatch failure is not
ordinary contention: fail closed and request owner-scoped intervention.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import time
from typing import Callable

from wait_for_cdb_writer_idle import GateBlocked, snapshot

APP_REPO = "BackstageTalks/tbt"
WORKFLOW = "cdb-drive-inbox.yml"


def await_idle_or_defer(
    max_seconds: int,
    interval_seconds: int,
    *,
    inspect: Callable[[], str] = snapshot,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """True if the writer is verified idle; False only after live contention."""
    if max_seconds < 0 or interval_seconds < 1:
        raise ValueError("Invalid writer wait budget")
    deadline = clock() + max_seconds
    while True:
        state = inspect()  # validates owner, tag SHA and owner lifecycle
        if state == "FREE":
            print("CDB_INBOX_WRITER_IDLE_VERIFIED", flush=True)
            return True
        if state != "BUSY":
            raise GateBlocked("Unexpected CDB writer lock state")
        now = clock()
        if now >= deadline:
            print("CDB_INBOX_WRITER_STILL_BUSY_REQUEUE_REQUIRED", flush=True)
            return False
        print("CDB_INBOX_WRITER_BUSY_WAITING", flush=True)
        sleep(min(interval_seconds, max(1, deadline - now)))


def enqueue_next_attempt(*, runner: Callable = subprocess.run) -> None:
    """Dispatch exactly one new main workflow, using the Actions-write token."""
    if (os.environ.get("GITHUB_REPOSITORY") != APP_REPO
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
        raise GateBlocked("CDB resume dispatch requires main workflow_dispatch context")
    token = os.environ.get("ACTIONS_DISPATCH_TOKEN")
    if not token:
        raise GateBlocked("Missing Actions-write token; CDB resume cannot be scheduled")
    environment = {**os.environ, "GH_TOKEN": token}
    runner(
        ["gh", "workflow", "run", WORKFLOW,
         "--repo", APP_REPO, "--ref", "main"],
        env=environment, check=True,
    )
    print("CDB_INBOX_RESUME_QUEUED_NOT_CDB_WRITTEN", flush=True)


def write_output(*, ready: bool) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise GateBlocked("Missing GITHUB_OUTPUT; cannot coordinate guarded job")
    with open(path, "a", encoding="utf-8") as out:
        out.write("ready=" + ("true" if ready else "false") + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-seconds", type=int, default=12600)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--requeue-only", action="store_true")
    args = parser.parse_args()
    if args.requeue_only:
        enqueue_next_attempt()
        return
    ready = await_idle_or_defer(args.max_seconds, args.interval_seconds)
    if not ready:
        # Queue before reporting deferred success, so failed dispatch is visible.
        enqueue_next_attempt()
    write_output(ready=ready)


if __name__ == "__main__":
    main()
