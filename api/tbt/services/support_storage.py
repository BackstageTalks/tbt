"""Minimal durable support-ticket storage for BlinQ.

The workflow is deliberately lightweight: users submit a request, admins can
change status and maintain an internal note. It is not intended to replace a
full helpdesk product.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
import uuid

from .admin_storage import AdminStorageUnavailable, _table

SUPPORT_TABLE = "BlinQSupport"
_ALLOWED_CATEGORIES = {"account", "membership", "predictions", "technical", "partnership", "privacy", "other"}
_ALLOWED_STATUS = {"new", "in_progress", "resolved"}
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _clean_email(value: object) -> str:
    email = str(value or "").strip().lower()[:254]
    if email and not _EMAIL_RE.fullmatch(email):
        raise ValueError("Invalid support email")
    return email


def build_support_ticket(payload: object, *, user: dict | None = None) -> tuple[dict, dict]:
    """Validate a request and build both public and storage representations.

    Keeping construction separate from persistence lets the public endpoint fall
    back to configured support e-mail when persistent storage is temporarily
    unavailable, while still failing closed when neither delivery path works.
    """
    if not isinstance(payload, dict):
        raise ValueError("Invalid support request")
    category = str(payload.get("category") or "other").strip().lower()
    if category not in _ALLOWED_CATEGORIES:
        raise ValueError("Invalid support category")
    message = str(payload.get("message") or "").strip()
    if len(message) < 8 or len(message) > 5000:
        raise ValueError("Support message must contain 8–5000 characters")
    user = user if isinstance(user, dict) else {}
    email = _clean_email(user.get("email") or payload.get("email"))
    if not email:
        raise ValueError("Support email is required")
    subject = str(payload.get("subject") or "").strip()[:160]
    now = datetime.now(timezone.utc)
    ticket_id = f"BLQ-{now.strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    entity = {
        "PartitionKey": "support",
        "RowKey": f"{int(now.timestamp()*1000):013d}-{uuid.uuid4().hex}",
        "ticket_id": ticket_id,
        "user_id": str(user.get("id") or user.get("uid") or "")[:256],
        "email": email,
        "account_plan": str(user.get("blinq_plan") or user.get("plan") or "")[:32],
        "category": category,
        "subject": subject,
        "message": message,
        "status": "new",
        "admin_note": "",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "updated_by": "",
    }
    public = {k: v for k, v in entity.items() if k not in {"PartitionKey", "RowKey"}}
    return public, entity


def create_support_ticket(payload: object, *, user: dict | None = None) -> dict:
    public, entity = build_support_ticket(payload, user=user)
    try:
        _table(SUPPORT_TABLE).create_entity(entity)
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to store support request") from exc
    return public


def list_support_tickets(*, status: str = "all", limit: int = 250) -> list[dict]:
    status = str(status or "all").strip().lower()
    if status not in _ALLOWED_STATUS | {"all"}:
        raise ValueError("Invalid support status")
    limit = max(1, min(500, int(limit)))
    try:
        rows = list(_table(SUPPORT_TABLE).query_entities(query_filter="PartitionKey eq 'support'"))
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to load support tickets") from exc
    if status != "all":
        rows = [row for row in rows if str(row.get("status") or "new") == status]
    rows.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
    return [{k: v for k, v in row.items() if k not in {"PartitionKey", "RowKey"}} for row in rows[:limit]]


def update_support_ticket(ticket_id: object, payload: object, *, actor_id: object) -> dict:
    ticket_id = str(ticket_id or "").strip()
    if not ticket_id or len(ticket_id) > 64:
        raise ValueError("Invalid ticket id")
    if not isinstance(payload, dict):
        raise ValueError("Invalid support update")
    status = str(payload.get("status") or "").strip().lower()
    if status and status not in _ALLOWED_STATUS:
        raise ValueError("Invalid support status")
    note = str(payload.get("admin_note") or "").strip()[:2000]
    client = _table(SUPPORT_TABLE)
    try:
        rows = list(client.query_entities(query_filter="PartitionKey eq 'support'"))
        current = next((row for row in rows if str(row.get("ticket_id") or "") == ticket_id), None)
        if not current:
            raise KeyError(ticket_id)
        entity = {
            "PartitionKey": "support",
            "RowKey": current["RowKey"],
            "status": status or str(current.get("status") or "new"),
            "admin_note": note,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": str(actor_id or "")[:256],
        }
        client.upsert_entity(entity, mode="merge")
        merged = dict(current)
        merged.update(entity)
        return {k: v for k, v in merged.items() if k not in {"PartitionKey", "RowKey"}}
    except KeyError:
        raise
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to update support ticket") from exc
