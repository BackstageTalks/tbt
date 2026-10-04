"""Admin-only, idempotent login observations from verified Firebase auth_time."""
from datetime import datetime, timezone
import hashlib
import math
from .admin_storage import _table, AdminStorageUnavailable

TABLE = "BlinQLoginMetrics"
TRACKING_STARTED_AT = "2026-10-04T15:05:00+00:00"
_START = datetime.fromisoformat(TRACKING_STARTED_AT).timestamp()

def _partition(user_id):
    uid=str(user_id or "").strip()
    if not uid or len(uid)>256: raise ValueError("Invalid user id")
    return hashlib.sha256(uid.encode()).hexdigest()

def record_login(user_id, auth_time, *, now=None):
    try: timestamp=float(auth_time)
    except (ValueError,TypeError): return False
    if not math.isfinite(timestamp): return False
    moment=now or datetime.now(timezone.utc)
    if timestamp<_START or timestamp>moment.timestamp()+60: return False
    entity={"PartitionKey":_partition(user_id),"RowKey":str(int(timestamp)),"signed_in_at":datetime.fromtimestamp(timestamp,timezone.utc).isoformat(),"observed_at":moment.isoformat()}
    try: _table(TABLE).create_entity(entity)
    except Exception as exc:
        if getattr(exc,"status_code",None)==409 or exc.__class__.__name__ in {"ResourceExistsError","AlreadyExists","_StorageWriteConflict"}: return False
        raise AdminStorageUnavailable("Unable to record login metrics") from exc
    return True

def load_login_statistics(user_ids, *, now=None):
    moment=now or datetime.now(timezone.utc)
    from zoneinfo import ZoneInfo
    today=moment.astimezone(ZoneInfo("Europe/Bratislava")).date()
    client=_table(TABLE)
    result={}
    try:
        for uid in {str(x or "").strip() for x in user_ids if x}:
            rows=list(client.query_entities(query_filter="PartitionKey eq '"+_partition(uid)+"'"))
            days=[datetime.fromisoformat(r["signed_in_at"]).astimezone(ZoneInfo("Europe/Bratislava")).date() for r in rows]
            result[uid]={"login_count":len(rows),"login_count_today":sum(d==today for d in days),"login_count_7d":sum(0<=(today-d).days<7 for d in days),"login_count_30d":sum(0<=(today-d).days<30 for d in days),"login_tracking_started_at":TRACKING_STARTED_AT}
    except Exception as exc: raise AdminStorageUnavailable("Unable to load login metrics") from exc
    return result
