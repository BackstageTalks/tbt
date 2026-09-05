"""Fail closed on ambiguous training labels; report coverage without API calls."""
from collections import Counter
from datetime import datetime, timezone


def audit_history(matches, now=None):
    now = now or datetime.now(timezone.utc)
    accepted, seen, events = [], set(), set()
    rejected = Counter()
    for m in sorted(matches, key=lambda m: (m.scheduled_at, m.match_id)):
        raw = m.provider_payload or {}
        event = next((str(raw[k]) for k in ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId", "id") if raw.get(k)), None)
        if m.scheduled_at.tzinfo is None:
            raise ValueError("Naive historical timestamp")
        if not m.is_completed:
            rejected["missing_result"] += 1
        elif m.scheduled_at >= now:
            rejected["future_result"] += 1
        elif not m.player1_id or not m.player2_id or m.player1_id == m.player2_id:
            rejected["invalid_players"] += 1
        elif m.match_id in seen or (event is not None and event in events):
            raise ValueError("Duplicate match/event identity in history; repair before training")
        else:
            seen.add(m.match_id)
            if event is not None:
                events.add(event)
            accepted.append(m)
    report = {"accepted": len(accepted), "rejected": dict(rejected),
              "by_tour": dict(Counter(m.tour for m in accepted)),
              "by_surface": dict(Counter(m.surface for m in accepted)),
              "by_year": dict(Counter(str(m.scheduled_at.year) for m in accepted)),
              "with_statistics": sum(any(v is not None for v in m.stats.values()) for m in accepted),
              "distinct_players": len({p for m in accepted for p in (m.player1_id, m.player2_id)})}
    return accepted, report
