"""Local-time clock for a single pre-dawn BlinQ morning refresh.

Provider calls use the real wall clock; only selection and publication-day
eligibility are evaluated against the upcoming 06:01 Bratislava boundary.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def morning_publication_at(
    now: datetime, *, start_hour: int = 6, timezone_name: str = "Europe/Bratislava"
) -> datetime:
    if now.tzinfo is None:
        raise ValueError("Morning refresh clock requires an aware datetime")
    if not 0 <= start_hour <= 23:
        raise ValueError("start_hour must be 0..23")
    local = now.astimezone(ZoneInfo(timezone_name))
    # The 1-minute margin makes the rollover unambiguous for GitHub deploys,
    # including CET/CEST transitions.
    publish_local = local.replace(
        hour=start_hour, minute=1, second=0, microsecond=0
    )
    return publish_local.astimezone(timezone.utc)


def morning_selection_now(
    now: datetime, *, start_hour: int = 6, timezone_name: str = "Europe/Bratislava"
) -> datetime:
    """Select the upcoming betting day before 06:00, never backdate after it."""
    return max(
        now,
        morning_publication_at(
            now, start_hour=start_hour, timezone_name=timezone_name
        ),
    )


def morning_publication_delay(
    now: datetime, *, start_hour: int = 6, timezone_name: str = "Europe/Bratislava"
) -> float:
    """Seconds to pause before making the private candidate deployable."""
    return max(
        0.0,
        (
            morning_publication_at(
                now, start_hour=start_hour, timezone_name=timezone_name
            ) - now
        ).total_seconds(),
    )
