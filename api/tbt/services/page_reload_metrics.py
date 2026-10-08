"""Per-authenticated-account browser reload events, separate from sign-in metrics."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import hashlib
import uuid
from .admin_storage import _table, AdminStorageUnavailable

TABLE = "BlinQPageReloadMetrics"
TRACKING_STARTED_AT = "2026-10-08T00:00:00+00:00"

def _partition(user_id):
    uid = str(user_id or "").strip()
    if not uid or len(uid) > 256:
        raise ValueError("Invalid user id")
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()

def record_reload(user_id, event_id, *, now=None):
    try:
        marker = str(uuid.UUID(str(event_id)))
        if marker != str(event_id).lower():
            return False
    except (ValueError, TypeError, AttributeError):
        return False
    moment = now or datetime.now(timezone.utc)
    entity = {"PartitionKey": _partition(user_id), "RowKey": marker,
              "reloaded_at": moment.isoformat()}
    try:
        _table(TABLE).create_entity(entity)
    except Exception as exc:
        if getattr(exc, "status_code", None) == 409 or exc.__class__.__name__ in {"ResourceExistsError", "AlreadyExists", "_StorageWriteConflict"}:
            return False
        raise AdminStorageUnavailable("Unable to record page reload") from exc
    return True

def load_reload_statistics(user_ids, *, now=None):
    moment = now or datetime.now(timezone.utc)
    today = moment.astimezone(ZoneInfo("Europe/Bratislava")).date()
    result = {}
    try:
        client = _table(TABLE)
        for uid in {str(x or "").strip() for x in user_ids if x}:
            rows = client.query_entities(query_filter="PartitionKey eq '" + _partition(uid) + "'")
            days = [datetime.fromisoformat(row["reloaded_at"]).astimezone(ZoneInfo("Europe/Bratislava")).date() for row in rows]
            result[uid] = {
                "reload_count_today": sum(d == today for d in days),
                "reload_count_7d": sum(0 <= (today-d).days < 7 for d in days),
                "reload_count_30d": sum(0 <= (today-d).days < 30 for d in days),
            }
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to load page reload statistics") from exc
    return result
