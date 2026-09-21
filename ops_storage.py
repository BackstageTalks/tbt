"""Small operational event journal used by the BlinQ admin System panel."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import uuid

from .admin_storage import AdminStorageUnavailable, _table

OPS_TABLE = "BlinQOpsEvents"
_ALLOWED_LEVELS = {"info", "warning", "error"}


def record_system_event(level: str, component: str, message: str, *, details: object = None) -> None:
    level = str(level or "info").strip().lower()
    if level not in _ALLOWED_LEVELS:
        level = "info"
    component = str(component or "app").strip()[:64]
    message = str(message or "").strip()[:500]
    if not message:
        return
    now = datetime.now(timezone.utc)
    entity = {
        "PartitionKey": now.strftime("%Y%m"),
        "RowKey": f"{int(now.timestamp()*1000):013d}-{uuid.uuid4().hex}",
        "level": level,
        "component": component,
        "message": message,
        "details_json": json.dumps(details or {}, ensure_ascii=False, separators=(",", ":"))[:8000],
        "occurred_at": now.isoformat(),
    }
    try:
        _table(OPS_TABLE).create_entity(entity)
    except Exception:
        # Observability must never take the product down if its own storage is unavailable.
        return


def list_system_events(*, hours: int = 24, limit: int = 100) -> dict:
    hours = max(1, min(24 * 30, int(hours)))
    limit = max(1, min(500, int(limit)))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    months = {cutoff.strftime("%Y%m"), now.strftime("%Y%m")}
    rows = []
    client = _table(OPS_TABLE)
    try:
        for partition in sorted(months):
            rows.extend(client.query_entities(query_filter=f"PartitionKey eq '{partition}'"))
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to read system events") from exc
    out = []
    counts = {"info": 0, "warning": 0, "error": 0}
    for row in rows:
        try:
            occurred = datetime.fromisoformat(str(row.get("occurred_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        if occurred < cutoff:
            continue
        level = str(row.get("level") or "info")
        counts[level] = counts.get(level, 0) + 1
        try:
            details = json.loads(str(row.get("details_json") or "{}"))
        except ValueError:
            details = {}
        out.append({
            "level": level,
            "component": str(row.get("component") or "app"),
            "message": str(row.get("message") or ""),
            "details": details if isinstance(details, dict) else {},
            "occurred_at": row.get("occurred_at"),
        })
    out.sort(key=lambda row: str(row.get("occurred_at") or ""), reverse=True)
    return {"hours": hours, "counts": counts, "items": out[:limit]}
