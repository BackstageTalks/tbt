"""Bounded, read-only polling for a busy BlinQ canonical CDB writer.

Never acquires, releases or steals the global single-writer lock.
The caller must revalidate the provider-day budget and dispatch window after waiting.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
