"""Cross-repository, fail-closed single-writer lock for BlinQ canonical CDB.

GitHub Actions concurrency groups DO NOT serialize different repositories.
An annotated tag ref in the PRIVATE data repository is created atomically.
Only the run that owns its exact tag-object SHA may verify/release it.

A canceled runner may leave a stale lock: intentionally never steal or
time-expire it automatically. Operator must inspect the owning run first.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

LOCK_REF = "refs/tags/blinq-cdb-global-writer"
LOCK_GET = "git/ref/tags/blinq-cdb-global-writer"
DEFAULT_REPOSITORY = "BackstageTalks/tbt-data"
DEFAULT_STATE = ".cdb-global-writer-lock.json"


def _api(repository: str, endpoint: str, *, method: str = "GET", data: dict | None = None) -> dict:
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("GH_TOKEN required for cross-repository CDB lock")
    command = ["gh", "api", "--method", method, f"repos/{repository}/{endpoint}"]
    if data is not None:
        command += ["--input", "-"]
    result = subprocess.run(
        command, input=json.dumps(data) if data is not None else None,
        text=True, capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"GitHub {method} {endpoint} failed: {(result.stderr or '')[:400]}"
        )
    return json.loads(result.stdout) if result.stdout.strip() else {}


def _remote_lock(repository: str) -> dict | None:
    try:
        return _api(repository, LOCK_GET)
    except RuntimeError as exc:
        # Treat only a positive HTTP 404 as absent; authorization or transport
        # failures must not be mistaken for an unlocked resource.
        if "HTTP 404" in str(exc):
            return None
        raise


def _owner() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    run = os.environ.get("GITHUB_RUN_ID", "").strip()
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "").strip()
    if not repo or not run or not attempt:
        raise RuntimeError("GitHub owner identity (repo/run/attempt) missing")
    return f"{repo}/actions/runs/{run}/attempts/{attempt}"


def _assert_ownership(repository: str, state: dict) -> None:
    if state.get("repository") != repository or state.get("owner") != _owner():
        raise RuntimeError("CDB lock state belongs to a different repository/run")
    remote = _remote_lock(repository)
    sha = (remote or {}).get("object", {}).get("sha")
    if not sha or sha != state.get("tag_sha"):
        raise RuntimeError("CDB lock missing or owned by a different writer")
    tag = _api(repository, f"git/tags/{sha}")
    if tag.get("message") != f"owner={state['owner']}":
        raise RuntimeError("CDB lock owner identity mismatch")


def acquire(repository: str, state_file: Path, *, wait_seconds: int = 1800,
            interval_seconds: int = 20) -> dict:
    if state_file.exists():
        raise RuntimeError("Refusing to overwrite existing local CDB lock state")
    owner = _owner()
    base = _api(repository, "git/ref/heads/main")
    main_sha = base.get("object", {}).get("sha")
    if not main_sha:
        raise RuntimeError("Cannot resolve canonical repository main for lock")
    tag = _api(repository, "git/tags", method="POST", data={
        "tag": "blinq-cdb-global-writer", "message": f"owner={owner}",
        "object": main_sha, "type": "commit",
    })
    tag_sha = tag.get("sha")
    if not tag_sha:
        raise RuntimeError("Cannot create independently owned CDB lock tag")
    deadline = time.monotonic() + max(0, wait_seconds)
    while True:
        try:
            _api(repository, "git/refs", method="POST",
                 data={"ref": LOCK_REF, "sha": tag_sha})
            state = {"schema": 1, "repository": repository,
                     "owner": owner, "tag_sha": tag_sha}
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
            _assert_ownership(repository, state)
            print(f"CDB global lock acquired: {owner}", flush=True)
            return state
        except RuntimeError:
            remote = _remote_lock(repository)
            if remote is None:
                # A failed create not explained by an existing lock is fatal.
                raise
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "CDB global writer busy; refusing concurrent release writes. "
                    "Inspect the lock tag and owner before manual cleanup."
                )
            time.sleep(max(1, interval_seconds))


def verify(repository: str, state_file: Path) -> dict:
    if not state_file.is_file():
        raise RuntimeError("Canonical CDB mutation blocked: global writer lock not acquired")
    state = json.loads(state_file.read_text(encoding="utf-8"))
    _assert_ownership(repository, state)
    return state


def release(repository: str, state_file: Path, *, if_held: bool = False) -> None:
    if if_held and not state_file.exists():
        return
    state = verify(repository, state_file)
    _api(repository, "git/refs/tags/blinq-cdb-global-writer", method="DELETE")
    state_file.unlink()
    print(f"CDB global lock released: {state['owner']}", flush=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("acquire", "verify", "release"))
    p.add_argument("--repository", default=os.environ.get("TBT_DATA_REPOSITORY", DEFAULT_REPOSITORY))
    p.add_argument("--state-file", type=Path, default=Path(DEFAULT_STATE))
    p.add_argument("--wait-seconds", type=int, default=1800)
    p.add_argument("--if-held", action="store_true")
    args = p.parse_args()
    if args.repository != DEFAULT_REPOSITORY:
        raise SystemExit("CDB global lock repository must be BackstageTalks/tbt-data")
    if args.action == "acquire":
        acquire(args.repository, args.state_file, wait_seconds=args.wait_seconds)
    elif args.action == "verify":
        verify(args.repository, args.state_file)
        print("CDB global writer ownership verified", flush=True)
    else:
        release(args.repository, args.state_file, if_held=args.if_held)


if __name__ == "__main__":
    main()
