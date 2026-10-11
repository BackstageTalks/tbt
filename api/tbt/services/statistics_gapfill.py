"""Shared eligibility for the API queue and collector; no provider calls."""
from datetime import datetime, timezone

TARGET_FIELDS = tuple(f"{side}_{field}" for side in ("p1", "p2") for field in
                      ("service_points_won", "return_points_won", "aces", "double_faults"))


def missing_fields(match):
    return [key for key in TARGET_FIELDS if (match.stats or {}).get(key) is None]


def event_id(match):
    raw = match.provider_payload or {}
    values = [raw.get(k) for k in
              ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId", "id")]
    identity = raw.get("_tbt_event_identity")
    if isinstance(identity, dict):
        values.append(identity.get("event_id"))
    ids = {str(v) for v in values if v is not None and str(v).isascii()
           and str(v).isdigit() and int(str(v)) > 0}
    # Conflicting identifiers must not select a provider event by precedence.
    return next(iter(ids)) if len(ids) == 1 else None


def retry_due(match, schema, now=None):
    now = now or datetime.now(timezone.utc)
    marker = (match.provider_payload or {}).get("_tbt_statistics", {})
    if not isinstance(marker, dict) or marker.get("schema") != schema or marker.get("event_id") != event_id(match):
        return True
    if marker.get("status") == "available" and not missing_fields(match):
        return False
    try:
        checked = datetime.fromisoformat(marker["fetched_at"].replace("Z", "+00:00"))
        if checked.tzinfo is None:
            return False
    except (KeyError, TypeError, ValueError, AttributeError):
        return False  # damaged retry metadata must not cause repeated paid calls
    recent = (now - match.scheduled_at).total_seconds() < 30 * 86400
    days = (7 if marker.get("status") == "available" else 1) if recent else 30
    if marker.get("status") == "conflict":
        days = 30
    return (now - checked).total_seconds() >= days * 86400
