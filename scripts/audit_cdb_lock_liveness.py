"""Read-only double-observation CDB lock/release status preflight.

No ref deletion, no CDB writes, no model actions and no paid API calls.
A completed owner is *only* a stale-lock candidate, never permission to unlock.
GitHub's ordinary DELETE ref endpoint has no documented expected-SHA CAS.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from typing import Callable

DATA_REPO = "BackstageTalks/tbt-data"
APP_REPO = "BackstageTalks/tbt"
LOCK_PATH = "git/ref/tags/blinq-cdb-global-writer"
TAG_PATH = "git/tags/"
RELEASE_PATH = "releases/tags/tbt-data-v1"
OWNER_RE = re.compile(
    r"^owner=(BackstageTalks/(?:tbt|tbt-data))/actions/runs/(\d+)/attempts/(\d+)$"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class AuditBlocked(RuntimeError):
    """An expected read-only safety fact could not be proved."""


def gh_get(repo: str, path: str) -> dict:
    """Authenticated GitHub REST GET only; never invokes a write method."""
    if not os.environ.get("GH_TOKEN"):
        raise AuditBlocked("GH_TOKEN required for authenticated read-only metadata")
    if repo not in {APP_REPO, DATA_REPO}:
        raise AuditBlocked("unsupported lock-owner repository")
    proc = subprocess.run(
        ["gh", "api", f"repos/{repo}/{path}"],
        text=True, capture_output=True, check=False,
    )
    if proc.returncode:
        # A positive 404 on the exact lock-ref GET is distinct from a
        # permission/rate-limit/network error. It never authorizes a writer.
        if path == LOCK_PATH and re.search(r"HTTP 404\\b", proc.stderr):
            return {"_lock_not_found": True}
        raise AuditBlocked("GitHub metadata read failed (never an unlock signal)")
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AuditBlocked("invalid GitHub metadata JSON") from exc
    if not isinstance(value, dict):
        raise AuditBlocked("unexpected GitHub metadata shape")
    return value


def _manifest_pin(release: dict) -> dict:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise AuditBlocked("release assets not verified")
    matching = [a for a in assets if isinstance(a, dict)
                and a.get("name") == "history_manifest.json"]
    if len(matching) != 1:
        raise AuditBlocked("history manifest asset missing or repeated")
    digest = matching[0].get("digest")
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise AuditBlocked("history manifest digest missing or malformed")
    return {"release_id": release.get("id"), "updated_at": release.get("updated_at"),
            "asset_count": len(assets), "history_manifest_digest": digest}


def assess(fetch: Callable[[str, str], dict]) -> dict:
    """Check owner/run liveness and ref+manifest consistency in two reads."""
    release_before = _manifest_pin(fetch(DATA_REPO, RELEASE_PATH))
    lock_before = fetch(DATA_REPO, LOCK_PATH)
    if lock_before.get("_lock_not_found") is True:
        # No owner can be verified when no ref exists. Record an observation,
        # not a lease, writer authorization, or CAS-safe unlock guarantee.
        lock_after = fetch(DATA_REPO, LOCK_PATH)
        release_after = _manifest_pin(fetch(DATA_REPO, RELEASE_PATH))
        stable = lock_after.get("_lock_not_found") is True and release_before == release_after
        return {
            "schema": "BLINQ_CDB_LOCK_LIVENESS_READONLY_V1",
            "classification": ("NO_LOCK_REF_AT_READ_TIME_ONLY" if stable
                               else "LOCK_OR_RELEASE_CHANGED_DURING_AUDIT"),
            "lock_sha_first": None,
            "lock_sha_second": lock_after.get("object", {}).get("sha"),
            "owner": None,
            "release_first": release_before,
            "release_second": release_after,
            "canonical_write_authorized": False,
            "lock_release_authorized": False,
            "delete_attempts": 0,
            "warning": "No lock observed is not a writer lease or atomic CAS guarantee",
        }
    lock_sha = lock_before.get("object", {}).get("sha")
    if not isinstance(lock_sha, str) or not SHA_RE.fullmatch(lock_sha):
        raise AuditBlocked("lock ref SHA missing or invalid")
    tag = fetch(DATA_REPO, TAG_PATH + lock_sha)
    if tag.get("sha") != lock_sha:
        raise AuditBlocked("annotated tag object does not match lock ref")
    identity = OWNER_RE.fullmatch(str(tag.get("message", "")).strip())
    if not identity:
        raise AuditBlocked("unrecognized writer owner; manual review required")
    owner_repo, owner_run_id, attempt = identity.groups()
    run = fetch(owner_repo, f"actions/runs/{owner_run_id}")
    if str(run.get("id")) != owner_run_id:
        raise AuditBlocked("owner run ID mismatch")
    status = run.get("status")
    conclusion = run.get("conclusion")
    if status not in {"queued", "in_progress", "completed"}:
        raise AuditBlocked("owner run status unverified")
    if status == "completed" and not conclusion:
        raise AuditBlocked("completed owner run lacks conclusion")

    # A double-read detects observable state changes. It is NOT an atomic CAS.
    lock_after = fetch(DATA_REPO, LOCK_PATH)
    release_after = _manifest_pin(fetch(DATA_REPO, RELEASE_PATH))
    if lock_after.get("object", {}).get("sha") != lock_sha:
        classification = "LOCK_CHANGED_DURING_AUDIT"
    elif release_before != release_after:
        classification = "CANONICAL_RELEASE_CHANGED_DURING_AUDIT"
    elif status in {"queued", "in_progress"}:
        classification = "ACTIVE_OR_PENDING_OWNER_DO_NOT_UNLOCK"
    else:
        classification = "COMPLETED_OWNER_STALE_CANDIDATE_ONLY"

    return {
        "schema": "BLINQ_CDB_LOCK_LIVENESS_READONLY_V1",
        "classification": classification,
        "lock_sha_first": lock_sha,
        "lock_sha_second": lock_after.get("object", {}).get("sha"),
        "owner": {"repo": owner_repo, "run_id": owner_run_id,
                  "attempt": attempt, "status": status, "conclusion": conclusion},
        "release_first": release_before,
        "release_second": release_after,
        "canonical_write_authorized": False,
        "lock_release_authorized": False,
        "delete_attempts": 0,
        "warning": "Cannot prove atomic CAS deletion from these metadata reads",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", help="Optional local path for audit JSON")
    args = parser.parse_args()
    try:
        report = assess(gh_get)
    except AuditBlocked as exc:
        # Fail closed and keep owner/private metadata out of error details.
        report = {"schema": "BLINQ_CDB_LOCK_LIVENESS_READONLY_V1",
                  "classification": "UNVERIFIED_BLOCKED",
                  "reason": str(exc), "lock_release_authorized": False,
                  "canonical_write_authorized": False, "delete_attempts": 0}
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_output:
        from pathlib import Path
        Path(args.json_output).write_text(payload, encoding="utf-8")
    print(payload, end="")
    if report["classification"] == "UNVERIFIED_BLOCKED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
