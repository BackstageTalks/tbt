"""Fail closed on ambiguous training labels; report coverage without API calls."""
from collections import Counter
from datetime import datetime, timezone
import math
from numbers import Real

from ..utils import is_rate_stat_field


def _statistics_issue(stats):
    """Return an exclusion reason for malformed canonical statistics.

    Missing statistics remain missing. Numeric zero is observed data.
    Canonical rate fields must already be normalized to the inclusive [0, 1] range.
    """
    if stats is None:
        return None
    if not isinstance(stats, dict):
        return "invalid_statistics"

    for key, value in stats.items():
        if value is None or value == "":
            continue
        if isinstance(value, bool) or not isinstance(value, Real):
            return "invalid_statistics"

        numeric = float(value)
        if not math.isfinite(numeric):
            return "invalid_statistics"

        if is_rate_stat_field(key) and not 0.0 <= numeric <= 1.0:
            return "invalid_statistics"

    return None


def _has_observed_statistics(stats) -> bool:
    """Count actual numeric observations without treating missing as zero."""
    if not isinstance(stats, dict):
        return False

    return any(
        value is not None
        and value != ""
        and isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        for value in stats.values()
    )


def audit_history(matches, now=None):
    now = now or datetime.now(timezone.utc)
    accepted, seen, events = [], set(), set()
    rejected = Counter()

    for m in sorted(matches, key=lambda m: (m.scheduled_at, m.match_id)):
        raw = m.provider_payload or {}
        event = next(
            (
                str(raw[k])
                for k in (
                    "_tbt_provider_event_id",
                    "provider_event_id",
                    "event_id",
                    "eventId",
                    "id",
                )
                if raw.get(k)
            ),
            None,
        )

        if m.scheduled_at.tzinfo is None:
            raise ValueError("Naive historical timestamp")
        if not str(m.match_id or "").strip():
            raise ValueError("Missing match identity in history")

        if not m.is_completed:
            rejected["missing_result"] += 1
        elif m.scheduled_at >= now:
            rejected["future_result"] += 1
        elif not m.player1_id or not m.player2_id or m.player1_id == m.player2_id:
            rejected["invalid_players"] += 1
        elif (stats_reason := _statistics_issue(m.stats)) is not None:
            rejected[stats_reason] += 1
        elif m.match_id in seen or (event is not None and event in events):
            raise ValueError(
                "Duplicate match/event identity in history; repair before training"
            )
        else:
            seen.add(m.match_id)
            if event is not None:
                events.add(event)
            accepted.append(m)

    report = {
        "accepted": len(accepted),
        "rejected": dict(rejected),
        "by_tour": dict(Counter(m.tour for m in accepted)),
        "by_surface": dict(Counter(m.surface for m in accepted)),
        "by_year": dict(Counter(str(m.scheduled_at.year) for m in accepted)),
        "with_statistics": sum(
            _has_observed_statistics(m.stats) for m in accepted
        ),
        "distinct_players": len(
            {
                player
                for m in accepted
                for player in (m.player1_id, m.player2_id)
            }
        ),
    }
    return accepted, report
