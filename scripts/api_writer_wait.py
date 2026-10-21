"""Bounded, read-only polling for a busy BlinQ canonical CDB writer.

Never acquires, releases or steals the global single-writer lock.
The caller must revalidate the provider-day budget and dispatch window after waiting.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.error import HTTPError
import re
from time import sleep
from typing import Callable


def wait_for_writer(
    check_writers: Callable[[], list[str]],
    deadline_utc: datetime,
    *,
    clock: Callable[[], datetime] | None = None,
    pause: Callable[[float], None] = sleep,
    poll_seconds: int = 45,
) -> bool:
    """Return whether we waited; fail closed if the window closes while busy.

    A transient occupied writer is not a successful no-op. Never retry API
    requests themselves here: this only polls the read-only GitHub writer state.
    """
    if deadline_utc.tzinfo is None:
        raise ValueError("An aware UTC deadline is required")
    if poll_seconds < 1:
        raise ValueError("poll_seconds must be positive")
    now_utc = clock or (lambda: datetime.now(timezone.utc))
    waited = False
    while True:
        active = check_writers()  # Errors propagate: unknown writer state fails closed.
        current = now_utc()
        if current.tzinfo is None:
            raise ValueError("An aware current time is required")
        if current >= deadline_utc:
            raise TimeoutError(
                "Canonical writer retry window expired; no API dispatch. "
                "A later scheduled tick must retry."
            )
        if not active:
            return waited
        print("Canonical writer busy; retrying after 45s: " + "; ".join(active), flush=True)
        pause(min(poll_seconds, max(1.0, (deadline_utc - current).total_seconds())))
        waited = True


def read_cdb_writer_lock(get_json, token: str) -> list[str]:
    """Read the authoritative cross-repository tag without modifying it.

    An Actions workflow inventory cannot see writers running in tbt-data.
    Verify private-repository access first, otherwise a 404 on the lock could
    be mistaken for an absent lock. Unknown/corrupt lock state fails closed.
    """
    if not token:
        raise RuntimeError("CDB private read token unavailable; refuse API dispatch")
    base = "https://api.github.com/repos/BackstageTalks/tbt-data/"
    head = get_json(base + "git/ref/heads/main", token)
    if (not isinstance(head, dict) or head.get("ref") != "refs/heads/main"
            or head.get("object", {}).get("type") != "commit"):
        raise RuntimeError("Cannot attest private CDB repository access")
    try:
        ref = get_json(base + "git/ref/tags/blinq-cdb-global-writer", token)
    except HTTPError as exc:
        if exc.code == 404:
            return []
        raise
    if (not isinstance(ref, dict)
            or ref.get("ref") != "refs/tags/blinq-cdb-global-writer"
            or ref.get("object", {}).get("type") != "tag"):
        raise RuntimeError("Unexpected global CDB writer tag ref; refuse dispatch")
    sha = str(ref["object"].get("sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("Invalid global CDB writer tag SHA")
    tag = get_json(base + "git/tags/" + sha, token)
    if not isinstance(tag, dict):
        raise RuntimeError("Global CDB writer annotation not readable")
    message = str(tag.get("message", "")).strip()
    if (not re.fullmatch(
            r"owner=[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/[0-9]+/attempts/[0-9]+",
            message)
            or tag.get("sha") != sha
            or tag.get("object", {}).get("type") != "commit"):
        raise RuntimeError("Invalid global CDB writer ownership evidence")
    return ["CDB global writer tag " + message]


