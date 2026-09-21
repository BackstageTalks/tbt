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




def _decode_daily_access_allocations(value: object) -> dict[str, list[str]]:
    if not value:
        return {}
    try:
        raw = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for section, items in raw.items():
        if not isinstance(items, list):
            continue
        clean = []
        for item in items[:20]:
            text = str(item or "").strip()
            if text and len(text) <= 96 and text not in clean:
                clean.append(text)
        name = str(section or "")[:32]
        if name:
            out[name] = clean
    return out


def save_daily_access_allocations(user_id: object, *, day: str, allocations: dict[str, list[str]]) -> dict:
    """Persist the current betting-day random entitlement allocation.

    One compact row per account is enough because only the current BlinQ betting
    day matters. Replacing yesterday's allocation is intentional.
    """
    uid = str(user_id or "").strip()
    key = _key(uid)
    day = str(day or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("Invalid daily access day")
    clean = _decode_daily_access_allocations(json.dumps(allocations or {}, ensure_ascii=False))
    now = datetime.now(timezone.utc).isoformat()
    entity = {
        "PartitionKey": "account",
        "RowKey": key,
        "user_id": uid,
        "daily_access_day": day,
        "daily_access_allocations_json": json.dumps(clean, ensure_ascii=False, separators=(",", ":")),
        "daily_access_updated_at": now,
    }
    try:
        _table(ACCOUNT_TABLE).upsert_entity(entity, mode="merge")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save daily access allocation") from exc
    return load_account_metadata(uid)


def _public_entity(entity: dict | None) -> dict:
    row = entity or {}
    avatar = str(row.get("avatar_variant") or "").strip().lower()
    if avatar not in {"m", "w"}:
        avatar = ""
    return {
        "telegram_nick": str(row.get("telegram_nick") or "")[:33],
        "avatar_variant": avatar,
        "payment_reference": str(row.get("payment_reference") or "")[:120],
        # Admin-only operational metadata. These values are intentionally kept
        # outside Firebase custom claims and are never returned by public_account().
        "tg_private_member": bool(row.get("tg_private_member", False)),
        "admin_note": str(row.get("admin_note") or "")[:500],
        "profile_updated_at": row.get("profile_updated_at"),
        "access_metadata_updated_at": row.get("access_metadata_updated_at"),
        "admin_metadata_updated_at": row.get("admin_metadata_updated_at"),
        "admin_metadata_updated_by": str(row.get("admin_metadata_updated_by") or "")[:256],
        "legal_consent_version": str(row.get("legal_consent_version") or "")[:40],
        "legal_consent_locale": str(row.get("legal_consent_locale") or "")[:8],
        "legal_consent_at": row.get("legal_consent_at"),
        "inactivity_warning_sent_at": row.get("inactivity_warning_sent_at"),
        "inactivity_user_warning_sent_at": row.get("inactivity_user_warning_sent_at"),
        "inactivity_deactivation_warning_sent_at": row.get("inactivity_deactivation_warning_sent_at"),
        "inactivity_expired_at": row.get("inactivity_expired_at"),
        # Durable per-user/day entitlement allocation. Stored as JSON in Azure
        # Table so refreshes/reorders cannot reveal a different random pick.
        "daily_access_day": str(row.get("daily_access_day") or "")[:16],
        "daily_access_allocations": _decode_daily_access_allocations(row.get("daily_access_allocations_json")),
        "daily_access_updated_at": row.get("daily_access_updated_at"),
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
    """Load only requested account rows; never scan the full account partition.

    Azure Table queries exact hashed RowKeys in bounded OR chunks. Firestore uses
    point reads because its compatibility adapter intentionally supports only the
    small query subset BlinQ needs. This keeps Admin pagination proportional to
    the current page rather than the total number of accounts.
    """
    wanted = {str(value or "").strip() for value in user_ids if str(value or "").strip()}
    if not wanted:
        return {}
    if len(wanted) > 500:
        raise ValueError("Too many account metadata rows requested")
    client = _table(ACCOUNT_TABLE)
    found: dict[str, dict] = {}
    try:
        if client.__class__.__name__ == "_FirestoreTableAdapter":
            for uid in wanted:
                try:
                    entity = client.get_entity(partition_key="account", row_key=_key(uid))
                except Exception as exc:
                    if _not_found(exc):
                        continue
                    raise
                if str(entity.get("user_id") or "") == uid:
                    found[uid] = _public_entity(entity)
        else:
            keyed = [(_key(uid), uid) for uid in wanted]
            for offset in range(0, len(keyed), 12):
                chunk = keyed[offset:offset + 12]
                row_filter = " or ".join(f"RowKey eq '{row_key}'" for row_key, _ in chunk)
                query = f"PartitionKey eq 'account' and ({row_filter})"
                for entity in client.query_entities(query_filter=query):
                    uid = str(entity.get("user_id") or "")
                    if uid in wanted:
                        found[uid] = _public_entity(entity)
        return {uid: found.get(uid, _public_entity(None)) for uid in wanted}
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to load account metadata") from exc




def delete_account_metadata(user_id: object) -> None:
    """Delete the single mutable profile row for an account.

    This is intentionally small and does not require an audit/payment ledger.
    Missing rows are treated as already deleted.
    """
    uid = str(user_id or "").strip()
    key = _key(uid)
    client = _table(ACCOUNT_TABLE)
    try:
        client.delete_entity(partition_key="account", row_key=key)
    except Exception as exc:
        if _not_found(exc):
            return
        raise AdminStorageUnavailable("Unable to delete account metadata") from exc


def normalize_profile_update(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Invalid profile update")
    allowed = {"telegram_nick", "blinq_avatar_variant", "display_name", "legal_consent_version", "legal_consent_locale"}
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

    legal_consent_version = str(payload.get("legal_consent_version") or "").strip()
    if len(legal_consent_version) > 40:
        raise ValueError("Legal consent version is too long")
    legal_consent_locale = str(payload.get("legal_consent_locale") or "").strip().lower()
    if legal_consent_locale and legal_consent_locale not in {"sk", "cz", "en"}:
        raise ValueError("Invalid legal consent locale")

    return {
        "telegram_nick": telegram,
        "avatar_variant": avatar,
        "display_name": display_name,
        "legal_consent_version": legal_consent_version,
        "legal_consent_locale": legal_consent_locale,
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
    if "legal_consent_version" in payload:
        # The timestamp is server-generated so registration records cannot forge
        # when consent was captured. The version identifies the JSON legal copy.
        entity["legal_consent_version"] = values["legal_consent_version"]
        entity["legal_consent_locale"] = values["legal_consent_locale"] or "sk"
        entity["legal_consent_at"] = now
    client = _table(ACCOUNT_TABLE)
    try:
        client.upsert_entity(entity, mode="merge")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save account profile") from exc
    merged = load_account_metadata(uid)
    return {**merged, "display_name": values["display_name"]}



def normalize_admin_metadata_update(payload: object) -> dict:
    """Validate admin-only account operations metadata.

    Telegram verification is deliberately out of scope for v1. The user supplies
    a nickname and the operator manually tracks whether the account is currently
    present in the private Telegram group.
    """
    if not isinstance(payload, dict):
        raise ValueError("Invalid admin metadata update")
    allowed = {"tg_private_member", "admin_note"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("Unsupported admin metadata field")

    values = {}
    if "tg_private_member" in payload:
        if not isinstance(payload.get("tg_private_member"), bool):
            raise ValueError("TG Private membership must be true or false")
        values["tg_private_member"] = payload["tg_private_member"]
    if "admin_note" in payload:
        note = str(payload.get("admin_note") or "").strip()
        if len(note) > 500:
            raise ValueError("Admin note is too long")
        values["admin_note"] = note
    return values


def save_admin_metadata(user_id: object, payload: object, *, actor_id: object = "") -> dict:
    uid = str(user_id or "").strip()
    key = _key(uid)
    values = normalize_admin_metadata_update(payload)
    now = datetime.now(timezone.utc).isoformat()
    entity = {
        "PartitionKey": "account",
        "RowKey": key,
        "user_id": uid,
        "admin_metadata_updated_at": now,
        "admin_metadata_updated_by": str(actor_id or "")[:256],
        **values,
    }
    client = _table(ACCOUNT_TABLE)
    try:
        client.upsert_entity(entity, mode="merge")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save account admin metadata") from exc
    return load_account_metadata(uid)


def save_inactivity_state(user_id: object, *, warning_sent_at: object = None, user_warning_sent_at: object = None, deactivation_warning_sent_at: object = None, expired_at: object = None) -> dict:
    """Persist worker-only inactivity markers used to de-duplicate e-mail notices."""
    uid = str(user_id or "").strip()
    key = _key(uid)
    entity = {"PartitionKey": "account", "RowKey": key, "user_id": uid}
    if warning_sent_at is not None:
        entity["inactivity_warning_sent_at"] = str(warning_sent_at or "")[:64]
    if user_warning_sent_at is not None:
        entity["inactivity_user_warning_sent_at"] = str(user_warning_sent_at or "")[:64]
    if deactivation_warning_sent_at is not None:
        entity["inactivity_deactivation_warning_sent_at"] = str(deactivation_warning_sent_at or "")[:64]
    if expired_at is not None:
        entity["inactivity_expired_at"] = str(expired_at or "")[:64]
    if len(entity) == 3:
        return load_account_metadata(uid)
    try:
        _table(ACCOUNT_TABLE).upsert_entity(entity, mode="merge")
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to save account inactivity state") from exc
    return load_account_metadata(uid)


def record_admin_metadata_audit(*, actor_id: object, target_id: object, before: dict, after: dict) -> None:
    actor = str(actor_id or "").strip()[:256]
    target = str(target_id or "").strip()[:256]
    if not actor or not target:
        raise ValueError("Audit actor and target are required")
    now = datetime.now(timezone.utc)
    before_safe = {
        "tg_private_member": bool((before or {}).get("tg_private_member", False)),
        "admin_note": str((before or {}).get("admin_note") or "")[:500],
    }
    after_safe = {
        "tg_private_member": bool((after or {}).get("tg_private_member", False)),
        "admin_note": str((after or {}).get("admin_note") or "")[:500],
    }
    entity = {
        "PartitionKey": now.strftime("%Y%m"),
        "RowKey": f"{int(now.timestamp()*1000):013d}-{uuid.uuid4().hex}",
        "actor_id": actor,
        "target_id": target,
        "action": "account_admin_metadata_update",
        "outcome": "success",
        "before_json": json.dumps(before_safe, ensure_ascii=False, separators=(",", ":")),
        "after_json": json.dumps(after_safe, ensure_ascii=False, separators=(",", ":")),
        "occurred_at": now.isoformat(),
    }
    client = _table(AUDIT_TABLE)
    try:
        client.create_entity(entity)
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to store account audit record") from exc

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

PAYMENTS_TABLE = "BlinQPayments"


def _safe_iso(value: object, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValueError("Date is required")
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid date") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_manual_payment(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Invalid payment")
    amount_raw = payload.get("amount")
    try:
        amount = round(float(amount_raw), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid payment amount") from exc
    if amount < 0 or amount > 1_000_000:
        raise ValueError("Invalid payment amount")
    currency = str(payload.get("currency") or "EUR").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Invalid payment currency")
    plan = str(payload.get("plan") or "").strip().lower()
    if plan not in {"rookie", "pro", "elite", "legend", "goat", "admin", "other"}:
        raise ValueError("Invalid payment plan")
    reference = str(payload.get("reference") or "").strip()[:120]
    note = str(payload.get("note") or "").strip()[:500]
    status = str(payload.get("status") or "confirmed").strip().lower()
    if status not in {"confirmed", "pending", "refunded", "cancelled"}:
        raise ValueError("Invalid payment status")
    return {
        "amount": amount,
        "currency": currency,
        "plan": plan,
        "reference": reference,
        "note": note,
        "status": status,
        "paid_at": _safe_iso(payload.get("paid_at") or datetime.now(timezone.utc).isoformat(), required=True),
        "valid_from": _safe_iso(payload.get("valid_from")),
        "valid_until": _safe_iso(payload.get("valid_until")),
    }


def record_manual_payment(user_id: object, payload: object, *, actor_id: object = "") -> dict:
    uid = str(user_id or "").strip()
    _key(uid)
    actor = str(actor_id or "").strip()[:256]
    if not actor:
        raise ValueError("Payment actor is required")
    values = normalize_manual_payment(payload)
    now = datetime.now(timezone.utc)
    payment_id = f"pay_{now.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:10]}"
    entity = {
        "PartitionKey": f"user:{_key(uid)}",
        "RowKey": f"{int(now.timestamp()*1000):013d}-{uuid.uuid4().hex}",
        "payment_id": payment_id,
        "user_id": uid,
        "actor_id": actor,
        "created_at": now.isoformat(),
        **values,
    }
    try:
        _table(PAYMENTS_TABLE).create_entity(entity)
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to store manual payment") from exc
    # Keep the most recent reference on the account row for quick filtering.
    if values.get("reference"):
        save_payment_reference(uid, values["reference"], actor_id=actor)
    return {k: v for k, v in entity.items() if k not in {"PartitionKey", "RowKey"}}


def list_manual_payments(user_id: object, *, limit: int = 100) -> list[dict]:
    uid = str(user_id or "").strip()
    key = _key(uid)
    limit = max(1, min(500, int(limit)))
    try:
        rows = list(_table(PAYMENTS_TABLE).query_entities(query_filter=f"PartitionKey eq 'user:{key}'"))
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to load manual payments") from exc
    rows.sort(key=lambda row: str(row.get("created_at") or row.get("paid_at") or ""), reverse=True)
    out = []
    for row in rows[:limit]:
        if str(row.get("user_id") or "") != uid:
            continue
        out.append({
            "payment_id": str(row.get("payment_id") or ""),
            "user_id": uid,
            "actor_id": str(row.get("actor_id") or ""),
            "amount": float(row.get("amount") or 0),
            "currency": str(row.get("currency") or "EUR"),
            "plan": str(row.get("plan") or ""),
            "reference": str(row.get("reference") or ""),
            "note": str(row.get("note") or ""),
            "status": str(row.get("status") or "confirmed"),
            "paid_at": row.get("paid_at"),
            "valid_from": row.get("valid_from"),
            "valid_until": row.get("valid_until"),
            "created_at": row.get("created_at"),
        })
    return out


def list_account_audit(*, target_id: object = "", limit: int = 100, months: int = 12) -> list[dict]:
    """Return recent access/admin audit records for the admin UI."""
    target = str(target_id or "").strip()
    limit = max(1, min(500, int(limit)))
    months = max(1, min(36, int(months)))
    now = datetime.now(timezone.utc)
    month_keys = []
    year, month = now.year, now.month
    for _ in range(months):
        month_keys.append(f"{year:04d}{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    rows = []
    client = _table(AUDIT_TABLE)
    try:
        for partition in month_keys:
            for row in client.query_entities(query_filter=f"PartitionKey eq '{partition}'"):
                if target and str(row.get("target_id") or "") != target:
                    continue
                rows.append(row)
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to load account audit") from exc
    rows.sort(key=lambda row: str(row.get("occurred_at") or ""), reverse=True)
    result = []
    for row in rows[:limit]:
        def parse_json(field):
            try:
                value = json.loads(str(row.get(field) or "{}"))
                return value if isinstance(value, dict) else {}
            except ValueError:
                return {}
        result.append({
            "actor_id": str(row.get("actor_id") or ""),
            "target_id": str(row.get("target_id") or ""),
            "action": str(row.get("action") or ""),
            "outcome": str(row.get("outcome") or ""),
            "occurred_at": row.get("occurred_at"),
            "before": parse_json("before_json"),
            "after": parse_json("after_json"),
        })
    return result
