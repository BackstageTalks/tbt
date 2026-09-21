"""Browser Web Push subscriptions with per-message membership audiences."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import logging
import os
from urllib.parse import urlparse

from .admin_storage import AdminStorageUnavailable, _table

PUSH_TABLE = "BlinQPushSubscriptions"
_MEMBERSHIP_LEVELS = {"rookie", "pro", "elite", "legend", "goat"}


def webpush_config() -> dict:
    public_key = str(os.getenv("BLINQ_WEBPUSH_PUBLIC_KEY") or "").strip()
    private_key = str(os.getenv("BLINQ_WEBPUSH_PRIVATE_KEY") or "").strip()
    subject = str(os.getenv("BLINQ_WEBPUSH_SUBJECT") or "").strip()
    enabled = bool(public_key and private_key and subject and (subject.startswith("mailto:") or subject.startswith("https://")))
    return {
        "enabled": enabled,
        "public_key": public_key if enabled else "",
        "subject_configured": bool(subject),
        "keys_configured": bool(public_key and private_key),
    }


def _subscription_row_key(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def _clean_subscription(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Invalid push subscription")
    endpoint = str(payload.get("endpoint") or "").strip()
    parsed = urlparse(endpoint)
    host = str(parsed.hostname or "").strip().lower().rstrip(".")
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or not host or len(endpoint) > 4096:
        raise ValueError("Invalid push endpoint")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Invalid push endpoint")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        address = None
    if address is not None and (
        address.is_private or address.is_loopback or address.is_link_local
        or address.is_multicast or address.is_reserved or address.is_unspecified
    ):
        raise ValueError("Invalid push endpoint")
    keys = payload.get("keys") or {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    if not (20 <= len(p256dh) <= 512 and 8 <= len(auth) <= 256):
        raise ValueError("Invalid push encryption keys")
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}


def save_subscription(*, user_id: str, subscription: object, plan: str, status: str, expires_at: object = None) -> dict:
    clean = _clean_subscription(subscription)
    user_id = str(user_id or "").strip()
    if not user_id:
        raise ValueError("Invalid push user")
    plan = str(plan or "").strip().lower()
    status = str(status or "").strip().lower()
    if plan not in _MEMBERSHIP_LEVELS:
        raise ValueError("Browser push requires an active BlinQ membership")
    if status not in {"active", "lifetime"}:
        raise ValueError("Active BlinQ membership is required for browser push")
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "PartitionKey": "push",
        "RowKey": _subscription_row_key(clean["endpoint"]),
        "user_id": user_id[:256],
        "endpoint": clean["endpoint"],
        "keys_json": json.dumps(clean["keys"], separators=(",", ":")),
        "plan": plan,
        "status": status,
        "expires_at": str(expires_at or "")[:64],
        "updated_at": now,
    }
    try:
        _table(PUSH_TABLE).upsert_entity(row, mode="replace")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save push subscription") from exc
    return {"ok": True, "subscribed": True, "endpoint_id": row["RowKey"][:16], "updated_at": now}


def delete_subscription(*, user_id: str, endpoint: str = "") -> dict:
    user_id = str(user_id or "").strip()
    if not user_id:
        raise ValueError("Invalid push user")
    endpoint = str(endpoint or "").strip()
    try:
        client = _table(PUSH_TABLE)
        rows = list(client.query_entities(query_filter="PartitionKey eq 'push'"))
        deleted = 0
        for row in rows:
            if str(row.get("user_id") or "") != user_id:
                continue
            if endpoint and str(row.get("endpoint") or "") != endpoint:
                continue
            client.delete_entity(partition_key="push", row_key=str(row.get("RowKey") or ""))
            deleted += 1
        return {"ok": True, "subscribed": False, "deleted": deleted}
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to delete push subscription") from exc


def sync_push_access(*, user_id: str, plan: str, status: str, expires_at: object = None) -> None:
    """Keep stored subscription entitlements in sync with admin access changes."""
    user_id = str(user_id or "").strip()
    if not user_id:
        return
    try:
        client = _table(PUSH_TABLE)
        rows = list(client.query_entities(query_filter="PartitionKey eq 'push'"))
        for row in rows:
            if str(row.get("user_id") or "") != user_id:
                continue
            row = dict(row)
            next_plan = str(plan or "").strip().lower()
            next_status = str(status or "").strip().lower()
            if next_status == "trial":
                next_plan, next_status = "rookie", "active"
            row["plan"] = next_plan
            row["status"] = next_status
            row["expires_at"] = str(expires_at or "")[:64]
            row["updated_at"] = datetime.now(timezone.utc).isoformat()
            client.upsert_entity(row, mode="replace")
    except Exception:
        logging.exception("Unable to sync browser-push access for user %s", user_id)


def _row_entitled(row: dict, levels: set[str]) -> bool:
    plan = str(row.get("plan") or "").lower()
    status = str(row.get("status") or "").lower()
    if plan not in levels or plan not in _MEMBERSHIP_LEVELS or status not in {"active", "lifetime"}:
        return False
    expires_at = str(row.get("expires_at") or "").strip()
    if status == "lifetime" or not expires_at:
        return True
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry > datetime.now(timezone.utc)
    except ValueError:
        return False


def _subscription_from_row(row: dict) -> dict | None:
    try:
        keys = json.loads(str(row.get("keys_json") or "{}"))
    except ValueError:
        return None
    endpoint = str(row.get("endpoint") or "")
    if not endpoint or not isinstance(keys, dict):
        return None
    return {"endpoint": endpoint, "keys": {"p256dh": str(keys.get("p256dh") or ""), "auth": str(keys.get("auth") or "")}}



def _insight_active_now(insight: dict) -> bool:
    if not insight.get("active", True):
        return False
    now = datetime.now(timezone.utc)
    for field, future_blocks in (("active_from", True), ("active_until", False)):
        raw = str(insight.get(field) or "").strip()
        if not raw:
            continue
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            moment = moment.astimezone(timezone.utc)
        except ValueError:
            return False
        if future_blocks and moment > now:
            return False
        if not future_blocks and moment <= now:
            return False
    return True

def dispatch_insight_push(insight: dict) -> dict:
    """Best-effort push after durable insight persistence; never blocks INFO/LIVE."""
    config = webpush_config()
    if not config["enabled"] or not isinstance(insight, dict) or not _insight_active_now(insight):
        return {"enabled": bool(config["enabled"]), "sent": 0, "failed": 0, "removed": 0}
    levels = {str(v).lower() for v in (insight.get("levels") or []) if str(v).lower() in _MEMBERSHIP_LEVELS}
    if not levels:
        return {"enabled": True, "sent": 0, "failed": 0, "removed": 0}
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logging.error("pywebpush is not installed; browser push disabled")
        return {"enabled": False, "sent": 0, "failed": 0, "removed": 0}

    try:
        client = _table(PUSH_TABLE)
        rows = list(client.query_entities(query_filter="PartitionKey eq 'push'"))
    except Exception as exc:
        logging.warning("Browser push subscription storage unavailable: %s", exc.__class__.__name__)
        return {"enabled": True, "sent": 0, "failed": 0, "removed": 0, "storage_unavailable": True}

    payload = json.dumps({
        "title": str(insight.get("title") or "BlinQ")[:140],
        "body": str(insight.get("body") or "")[:420],
        "url": str(insight.get("link") or "/#predictions")[:1000],
        "tag": str(insight.get("id") or "blinq-info")[:120],
        "type": str(insight.get("type") or "info")[:40],
        "priority": str(insight.get("priority") or "normal")[:20],
    }, ensure_ascii=False, separators=(",", ":"))
    ttl = 600 if str(insight.get("type") or "") in {"live_watch", "alert", "set2"} else 6 * 3600
    sent = failed = removed = 0
    for row in rows:
        if not _row_entitled(row, levels):
            continue
        subscription = _subscription_from_row(row)
        if not subscription:
            continue
        try:
            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=str(os.getenv("BLINQ_WEBPUSH_PRIVATE_KEY") or "").strip(),
                vapid_claims={"sub": str(os.getenv("BLINQ_WEBPUSH_SUBJECT") or "").strip()},
                ttl=ttl,
            )
            sent += 1
        except WebPushException as exc:
            failed += 1
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {404, 410}:
                try:
                    client.delete_entity(partition_key="push", row_key=str(row.get("RowKey") or ""))
                    removed += 1
                except Exception:
                    pass
        except Exception:
            failed += 1
    return {"enabled": True, "sent": sent, "failed": failed, "removed": removed}


def push_storage_diagnostics() -> dict:
    config = webpush_config()
    count = None
    storage_available = False
    try:
        rows = list(_table(PUSH_TABLE).query_entities(query_filter="PartitionKey eq 'push'"))
        count = len(rows)
        storage_available = True
    except Exception:
        pass
    return {**config, "storage_available": storage_available, "subscriptions": count}
