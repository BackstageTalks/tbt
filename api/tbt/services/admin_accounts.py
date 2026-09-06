"""Admin-only Supabase Auth account management helpers.

This module manages identity/account metadata only. It never stores tennis data.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .auth import AuthUnavailable, PAID_PLANS


ALLOWED_STATUSES = {"active", "expired", "suspended", "lifetime"}
ALLOWED_ROLES = {"user", "admin"}


def _headers(cfg):
    key = str(getattr(cfg, "supabase_service_role_key", "") or "").strip()
    url = str(getattr(cfg, "supabase_url", "") or "").strip()
    if not key or not url:
        raise AuthUnavailable("Admin account management is not configured")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request_json(response):
    if response.status_code in (401, 403):
        raise AuthUnavailable("Supabase admin access denied")
    if response.status_code < 200 or response.status_code >= 300:
        raise AuthUnavailable(f"Supabase admin request failed ({response.status_code})")
    try:
        payload = response.json()
    except ValueError as exc:
        raise AuthUnavailable("Supabase admin response is invalid") from exc
    if not isinstance(payload, dict):
        raise AuthUnavailable("Supabase admin response is invalid")
    return payload


def list_users(cfg, *, page=1, per_page=100, client=None):
    page = max(1, int(page))
    per_page = max(1, min(200, int(per_page)))
    own = client is None
    client = client or httpx.Client(timeout=15)
    try:
        response = client.get(
            f"{cfg.supabase_url}/auth/v1/admin/users",
            headers=_headers(cfg),
            params={"page": page, "per_page": per_page},
        )
        payload = _request_json(response)
        users = payload.get("users")
        if not isinstance(users, list):
            raise AuthUnavailable("Supabase admin response lacks users")
        return users
    except httpx.HTTPError as exc:
        raise AuthUnavailable("Supabase admin service temporarily unavailable") from exc
    finally:
        if own:
            client.close()


def get_user(cfg, user_id, *, client=None):
    user_id = str(user_id or "").strip()
    if not user_id or len(user_id) > 256:
        raise ValueError("Invalid user id")
    own = client is None
    client = client or httpx.Client(timeout=15)
    try:
        response = client.get(
            f"{cfg.supabase_url}/auth/v1/admin/users/{user_id}",
            headers=_headers(cfg),
        )
        payload = _request_json(response)
        if not payload.get("id"):
            raise AuthUnavailable("Supabase user response is invalid")
        return payload
    except httpx.HTTPError as exc:
        raise AuthUnavailable("Supabase admin service temporarily unavailable") from exc
    finally:
        if own:
            client.close()


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
    if status == "active" and not plan:
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


def update_user_access(cfg, user_id, payload, *, actor_id="", client=None):
    changes = normalize_access_update(payload)
    own = client is None
    client = client or httpx.Client(timeout=15)
    try:
        current = get_user(cfg, user_id, client=client)
        app = dict(current.get("app_metadata") or {})
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

        response = client.put(
            f"{cfg.supabase_url}/auth/v1/admin/users/{str(user_id).strip()}",
            headers=_headers(cfg),
            json={"app_metadata": app},
        )
        return _request_json(response)
    except httpx.HTTPError as exc:
        raise AuthUnavailable("Supabase admin service temporarily unavailable") from exc
    finally:
        if own:
            client.close()
