"""Admin-only Firebase identity account management helpers.

This module manages identity/account metadata only and never tennis data.
"""
from __future__ import annotations

from datetime import datetime, timezone


from .auth import (
    AuthUnavailable,
    PAID_PLANS,
    _firebase_modules,
    firebase_app,
    firebase_configured,
    firebase_get_user,
    firebase_user_to_dict,
)


ALLOWED_STATUSES = {"active", "expired", "suspended", "lifetime"}
ALLOWED_ROLES = {"user", "admin"}


def _firebase_list_users(cfg, *, page=1, per_page=100):
    _, firebase_auth, _ = _firebase_modules()
    app = firebase_app(cfg)
    try:
        result = firebase_auth.list_users(max_results=per_page, app=app)
        current_page = 1
        while result is not None and current_page < page:
            result = result.get_next_page()
            current_page += 1
        if result is None:
            return []
        return [firebase_user_to_dict(record) for record in result.users]
    except Exception as exc:
        raise AuthUnavailable("Firebase admin service temporarily unavailable") from exc


def list_users(cfg, *, page=1, per_page=100, client=None):
    page = max(1, int(page))
    per_page = max(1, min(200, int(per_page)))
    if not firebase_configured(cfg):
        raise AuthUnavailable("Firebase admin account management is not configured")
    return _firebase_list_users(cfg, page=page, per_page=per_page)


def get_user(cfg, user_id, *, client=None):
    user_id = str(user_id or "").strip()
    if not user_id or len(user_id) > 256:
        raise ValueError("Invalid user id")
    if not firebase_configured(cfg):
        raise AuthUnavailable("Firebase admin account management is not configured")
    user = firebase_get_user(cfg, user_id)
    if not user:
        raise AuthUnavailable("Firebase user does not exist")
    return user


def _clean_text(value, *, max_len):
    text = str(value or "").strip()
    return text[:max_len]


def _validate_expires_at(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Invalid expiration date")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid expiration date") from exc
    if parsed.tzinfo is None:
        raise ValueError("Expiration date must include timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_access_update(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid access update")

    role = _clean_text(payload.get("role"), max_len=16).lower() or "user"
    plan = _clean_text(payload.get("plan"), max_len=16).lower()
    status = _clean_text(payload.get("status"), max_len=16).lower() or "expired"
    expires_at = _validate_expires_at(payload.get("expires_at"))
    payment_reference = _clean_text(payload.get("payment_reference"), max_len=120)

    if role not in ALLOWED_ROLES:
        raise ValueError("Invalid role")
    if plan and plan not in PAID_PLANS:
        raise ValueError("Invalid plan")
    if status not in ALLOWED_STATUSES:
        raise ValueError("Invalid status")
    if status == "lifetime" and plan != "goat":
        raise ValueError("Lifetime status is reserved for GOAT")
    if status == "lifetime":
        expires_at = None
    if status == "active" and not plan and role != "admin":
        raise ValueError("Active status requires a plan")
    if status == "active" and plan and expires_at is None:
        raise ValueError("Active non-lifetime plan requires an expiration date")

    return {
        "role": role,
        "plan": plan,
        "status": status,
        "expires_at": expires_at,
        "payment_reference": payment_reference,
    }


def _apply_access_metadata(app, changes, actor_id):
    app = dict(app or {})
    app["role"] = changes["role"]

    if changes["plan"]:
        app["blinq_plan"] = changes["plan"]
    else:
        app.pop("blinq_plan", None)

    app["blinq_status"] = changes["status"]
    if changes["expires_at"]:
        app["blinq_expires_at"] = changes["expires_at"]
    else:
        app.pop("blinq_expires_at", None)

    if changes["payment_reference"]:
        app["blinq_payment_reference"] = changes["payment_reference"]
    else:
        app.pop("blinq_payment_reference", None)

    app["blinq_access_updated_at"] = datetime.now(timezone.utc).isoformat()
    if actor_id:
        app["blinq_access_updated_by"] = str(actor_id)[:256]
    return app


def _update_firebase_user_access(cfg, user_id, changes, *, actor_id=""):
    _, firebase_auth, _ = _firebase_modules()
    app = firebase_app(cfg)
    try:
        record = firebase_auth.get_user(str(user_id).strip(), app=app)
        claims = _apply_access_metadata(record.custom_claims or {}, changes, actor_id)
        firebase_auth.set_custom_user_claims(str(user_id).strip(), claims, app=app)
        updated = firebase_auth.get_user(str(user_id).strip(), app=app)
        return firebase_user_to_dict(updated)
    except Exception as exc:
        raise AuthUnavailable("Firebase admin service temporarily unavailable") from exc


def update_user_access(cfg, user_id, payload, *, actor_id="", client=None):
    changes = normalize_access_update(payload)
    if not firebase_configured(cfg):
        raise AuthUnavailable("Firebase admin account management is not configured")
    return _update_firebase_user_access(cfg, user_id, changes, actor_id=actor_id)
