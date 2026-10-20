"""Bounded CDB Drive Inbox catch-up: one validated batch triggers at most one more.

No import work or private data appears here. This runs only after the source
checkpoint was CAS-committed, independently read back, and the global writer
was safely released by the main guarded workflow. A low immutable hop budget
prevents runaway dispatch even when Drive files keep changing.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from typing import Callable

MAX_REMAINING = 6
APP_REPO = "BackstageTalks/tbt"
WORKFLOW = "cdb-drive-inbox.yml"
MANIFEST = Path("work/drive_manifest.json")


class CatchupBlocked(RuntimeError):
    """Required evidence missing or an unsafe dispatch was requested."""


def next_budget(remaining: int, manifest: dict | None) -> int | None:
    if not isinstance(remaining, int) or isinstance(remaining, bool) or not 0 <= remaining <= MAX_REMAINING:
        raise CatchupBlocked("Invalid or excessive catch-up budget")
    if remaining == 0 or manifest is None:
        return None
    if (not isinstance(manifest, dict) or manifest.get("schema") != 2
            or manifest.get("state") != "DRIVE_SOURCE_FETCH_ONLY"
            or manifest.get("production_mutated") is not False
            or manifest.get("api_requests") != 0):
        raise CatchupBlocked("Untrusted Drive source manifest")
    pending, fetched = manifest.get("pending_supported"), manifest.get("fetched")
    if (not isinstance(pending, int) or isinstance(pending, bool) or pending < 0
            or not isinstance(fetched, int) or isinstance(fetched, bool)
            or not 0 <= fetched <= 100):
        raise CatchupBlocked("Invalid Drive batch counts")
    if fetched == 0 or pending == 0:
        return None
    return remaining - 1


def queue_next(remaining: int, *,
               manifest_path: Path = MANIFEST,
               runner: Callable = subprocess.run) -> bool:
    if (os.environ.get("GITHUB_REPOSITORY") != APP_REPO
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
        raise CatchupBlocked("Catch-up may only chain the production main dispatch")
    token = os.environ.get("ACTIONS_DISPATCH_TOKEN")
    if not token:
        raise CatchupBlocked("Missing Actions-write token for bounded CDB catch-up")
    if remaining and not manifest_path.exists():
        print("CDB_INBOX_CATCHUP_NO_FRESH_DRIVE_MANIFEST", flush=True)
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if remaining else None
    following = next_budget(remaining, manifest)
    if following is None:
        print("CDB_INBOX_CATCHUP_NO_FURTHER_BATCH_REQUIRED", flush=True)
        return False
    # GITHUB_TOKEN is used only for triggering the same constrained workflow;
    # the private CDB token must never be leaked to the Actions endpoint.
    environ = {**os.environ, "GH_TOKEN": token}
    runner(["gh", "workflow", "run", WORKFLOW,
            "--repo", APP_REPO, "--ref", "main",
            "-f", f"catchup_remaining={following}"],
           env=environ, check=True)
    print(f"CDB_INBOX_CATCHUP_NEXT_BATCH_QUEUED remaining={following}", flush=True)
    return True


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--remaining", type=int, required=True)
    args = p.parse_args()
    queue_next(args.remaining)


if __name__ == "__main__":
    main()
