"""Admin-owned retention controls for login and page-reload telemetry.

Do not mix telemetry erasure with immutable access audit or manual TG queue.
"""
from datetime import datetime, timezone

from .admin_storage import AdminStorageUnavailable, _table
from .account_storage import ACTIVITY_SETTINGS_TABLE, _not_found
from .login_metrics import TABLE as LOGIN_TABLE
from .page_reload_metrics import TABLE as RELOAD_TABLE

_ALLOWED_DAYS = {7, 14, 30, 60, 90, 180, 365}


def load_account_telemetry_settings() -> dict:
    try:
        row = _table(ACTIVITY_SETTINGS_TABLE).get_entity(
            partition_key="global", row_key="settings"
        )
    except Exception as exc:
        if _not_found(exc):
            return {"retention_days": 90}
        raise AdminStorageUnavailable("Unable to load account telemetry retention") from exc
    days = int(row.get("telemetry_retention_days") or 90)
    return {"retention_days": max(7, min(365, days))}


def save_account_telemetry_settings(days: object) -> dict:
    try:
        days = int(days)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid telemetry retention") from exc
    if days not in _ALLOWED_DAYS:
        raise ValueError("Unsupported telemetry retention period")
    try:
        _table(ACTIVITY_SETTINGS_TABLE).upsert_entity({
            "PartitionKey": "global", "RowKey": "settings",
            "telemetry_retention_days": days,
            "telemetry_updated_at": datetime.now(timezone.utc).isoformat(),
        }, mode="merge")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to update telemetry retention") from exc
    return {"retention_days": days}


def prune_account_telemetry(*, all_events: bool = False) -> dict:
    """Purge only login + refresh metrics, preserving account and audit tables."""
    if not isinstance(all_events, bool):
        raise ValueError("Invalid telemetry clear option")
    retention = load_account_telemetry_settings()["retention_days"]
    cutoff = datetime.now(timezone.utc).timestamp() - retention * 86400
    counts = {"logins": 0, "reloads": 0}
    for table, column, label in (
        (LOGIN_TABLE, "signed_in_at", "logins"),
        (RELOAD_TABLE, "reloaded_at", "reloads"),
    ):
        client = _table(table)
        try:
            for row in client.query_entities():
                try:
                    timestamp = datetime.fromisoformat(
                        str(row.get(column) or "").replace("Z", "+00:00")
                    ).timestamp()
                except (ValueError, TypeError):
                    continue
                if all_events or timestamp < cutoff:
                    client.delete_entity(
                        partition_key=row["PartitionKey"],
                        row_key=row["RowKey"],
                    )
                    counts[label] += 1
        except Exception as exc:
            raise AdminStorageUnavailable("Unable to remove telemetry history") from exc
    return {"deleted": sum(counts.values()), **counts}
