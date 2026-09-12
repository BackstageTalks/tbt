"""Non-authentication BlinQ account metadata and append-only audit storage.

Firebase custom claims are reserved for authorization only. User profile fields,
payment references and audit history live in Azure Table Storage so they cannot
race with membership/role claim updates or leak into Firebase ID tokens.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import uuid

from .admin_storage import AdminStorageUnavailable, _table


ACCOUNT_TABLE = "BlinQAccounts"
AUDIT_TABLE = "BlinQAccountAudit"
_TELEGRAM_RE = re.compile(r"^@?[A-Za-z0-9_]{5,32}$")


def _key(user_id: object) -> str:
    text = str(user_id or "").strip()
    if not text or len(text) > 256:
        raise ValueError("Invalid user id")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _not_found(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    name = exc.__class__.__name__.lower()
    return status == 404 or "resourcenotfound" in name or isinstance(exc, KeyError)


def _public_entity(entity: dict | None) -> dict:
    row = entity or {}
    avatar = str(row.get("avatar_variant") or "").strip().lower()
    if avatar not in {"m", "w"}:
        avatar = ""
    return {
        "telegram_nick": str(row.get("telegram_nick") or "")[:33],
        "avatar_variant": avatar,
        "payment_reference": str(row.get("payment_reference") or "")[:120],
        "profile_updated_at": row.get("profile_updated_at"),
        "access_metadata_updated_at": row.get("access_metadata_updated_at"),
    }


def load_account_metadata(user_id: object) -> dict:
    uid = str(user_id or "").strip()
    key = _key(uid)
    client = _table(ACCOUNT_TABLE)
    try:
        entity = client.get_entity(partition_key="account", row_key=key)
    except Exception as exc:
        if _not_found(exc):
            return _public_entity(None)
        raise AdminStorageUnavailable("Unable to load account metadata") from exc
    # A hash collision is astronomically unlikely, but never return metadata for
    # a different uid if storage is corrupted or manually edited.
    if str(entity.get("user_id") or "") != uid:
        raise AdminStorageUnavailable("Account metadata integrity check failed")
    return _public_entity(entity)


def load_account_metadata_many(user_ids: list[object]) -> dict[str, dict]:
    wanted = {str(value or "").strip() for value in user_ids if str(value or "").strip()}
    if not wanted:
        return {}
    if len(wanted) > 500:
        raise ValueError("Too many account metadata rows requested")
    client = _table(ACCOUNT_TABLE)
    try:
        rows = client.query_entities(query_filter="PartitionKey eq 'account'")
        found = {}
        for entity in rows:
            uid = str(entity.get("user_id") or "")
            if uid in wanted:
                found[uid] = _public_entity(entity)
        return {uid: found.get(uid, _public_entity(None)) for uid in wanted}
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to load account metadata") from exc


def normalize_profile_update(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Invalid profile update")
    allowed = {"telegram_nick", "blinq_avatar_variant", "display_name"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("Unsupported profile field")

    telegram = str(payload.get("telegram_nick") or "").strip()
    if telegram:
        if not _TELEGRAM_RE.fullmatch(telegram):
            raise ValueError("Telegram username must contain 5–32 letters, digits or underscores")
        if not telegram.startswith("@"):
            telegram = "@" + telegram

    avatar = str(payload.get("blinq_avatar_variant") or "").strip().lower()
    if avatar not in {"", "m", "w"}:
        raise ValueError("Invalid avatar style")

    display_name = str(payload.get("display_name") or "").strip()
    if len(display_name) > 80:
        raise ValueError("Display name is too long")

    return {
        "telegram_nick": telegram,
        "avatar_variant": avatar,
        "display_name": display_name,
    }


def save_profile_metadata(user_id: object, payload: object) -> dict:
    uid = str(user_id or "").strip()
    key = _key(uid)
    values = normalize_profile_update(payload)
    now = datetime.now(timezone.utc).isoformat()
    entity = {
        "PartitionKey": "account",
        "RowKey": key,
        "user_id": uid,
        "profile_updated_at": now,
    }
    # Profile updates are PATCH-like: changing a display name must not silently
    # wipe Telegram/avatar metadata, and changing an avatar must not wipe Telegram.
    if "telegram_nick" in payload:
        entity["telegram_nick"] = values["telegram_nick"]
    if "blinq_avatar_variant" in payload:
        entity["avatar_variant"] = values["avatar_variant"]
    client = _table(ACCOUNT_TABLE)
    try:
        client.upsert_entity(entity, mode="merge")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save account profile") from exc
    merged = load_account_metadata(uid)
    return {**merged, "display_name": values["display_name"]}


def save_payment_reference(user_id: object, value: object, *, actor_id: object = "") -> dict:
    uid = str(user_id or "").strip()
    key = _key(uid)
    reference = str(value or "").strip()
    if len(reference) > 120:
        raise ValueError("Payment reference is too long")
    now = datetime.now(timezone.utc).isoformat()
    entity = {
        "PartitionKey": "account",
        "RowKey": key,
        "user_id": uid,
        "payment_reference": reference,
        "access_metadata_updated_at": now,
        "access_metadata_updated_by": str(actor_id or "")[:256],
    }
    client = _table(ACCOUNT_TABLE)
    try:
        client.upsert_entity(entity, mode="merge")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save account access metadata") from exc
    return _public_entity(entity)


def record_access_audit(*, actor_id: object, target_id: object, before: dict, after: dict, outcome: str = "success") -> None:
    actor = str(actor_id or "").strip()[:256]
    target = str(target_id or "").strip()[:256]
    if not actor or not target:
        raise ValueError("Audit actor and target are required")
    now = datetime.now(timezone.utc)
    allowed = ("role", "plan", "status", "expires_at")
    before_safe = {key: before.get(key) for key in allowed}
    after_safe = {key: after.get(key) for key in allowed}
    entity = {
        "PartitionKey": now.strftime("%Y%m"),
        "RowKey": f"{int(now.timestamp()*1000):013d}-{uuid.uuid4().hex}",
        "actor_id": actor,
        "target_id": target,
        "action": "account_access_update",
        "outcome": str(outcome or "success")[:24],
        "before_json": json.dumps(before_safe, ensure_ascii=False, separators=(",", ":")),
        "after_json": json.dumps(after_safe, ensure_ascii=False, separators=(",", ":")),
        "occurred_at": now.isoformat(),
    }
    client = _table(AUDIT_TABLE)
    try:
        client.create_entity(entity)
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to store account audit record") from exc
