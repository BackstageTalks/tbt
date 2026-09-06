"""Supabase is used solely for identity/account metadata, never tennis storage."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx


class AuthUnavailable(RuntimeError):
    pass


PAID_PLANS = {"rookie", "pro", "elite", "legend", "goat"}
PLAN_LABELS = {
    "trial": "Rookie Trial",
    "expired": "Expired",
    "rookie": "Rookie",
    "pro": "PRO",
    "elite": "Elite",
    "legend": "Legend",
    "goat": "GOAT",
    "admin": "Admin",
}


def request_authorization(headers):
    """Return the user bearer token without trusting SWA's rewritten Authorization header."""
    custom = str(headers.get("X-Blinq-Access-Token") or "").strip()
    if custom:
        return custom if custom.lower().startswith("bearer ") else f"Bearer {custom}"
    return headers.get("Authorization")


def verify_user(authorization, cfg, client=None):
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if not token or len(token) > 16384:
        return None
    if not cfg.supabase_url or not cfg.supabase_anon_key:
        raise AuthUnavailable("Authentication is not configured")
    own = client is None
    client = client or httpx.Client(timeout=10)
    try:
        response = client.get(f"{cfg.supabase_url}/auth/v1/user", headers={
            "apikey": cfg.supabase_anon_key, "Authorization": f"Bearer {token}"})
        if response.status_code in (401, 403):
            return None
        if response.status_code != 200:
            raise AuthUnavailable("Identity service temporarily unavailable")
        user = response.json()
        return user if isinstance(user, dict) and user.get("id") else None
    except (httpx.HTTPError, ValueError) as exc:
        raise AuthUnavailable("Identity service temporarily unavailable") from exc
    finally:
        if own:
            client.close()


def _parse_utc(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _admin_email_set(cfg):
    raw = str(getattr(cfg, "blinq_admin_emails", "") or "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def is_admin(user, cfg=None):
    if not isinstance(user, dict):
        return False
    app = user.get("app_metadata") or {}
    if str(app.get("role") or "").strip().lower() == "admin":
        return True
    if cfg is not None:
        email = str(user.get("email") or "").strip().lower()
        if email and email in _admin_email_set(cfg):
            return True
    return False


def account_access(user, *, cfg=None, now=None):
    """Resolve role/plan state from admin-controlled app metadata and signup time.

    Trial is derived, not stored: an account without active paid access gets 72 hours
    from Supabase's immutable created_at timestamp. Paid access is intentionally kept
    in app_metadata so a normal user cannot grant themselves a plan via /auth/v1/user.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("account_access requires timezone-aware now")
    now = now.astimezone(timezone.utc)

    app = user.get("app_metadata") or {}
    admin = is_admin(user, cfg)
    created_at = _parse_utc(user.get("created_at"))
    trial_expires = created_at + timedelta(hours=72) if created_at else None

    if admin:
        return {
            "role": "admin",
            "plan": "admin",
            "plan_label": PLAN_LABELS["admin"],
            "status": "active",
            "expires_at": None,
            "trial_expires_at": trial_expires.isoformat() if trial_expires else None,
            "is_admin": True,
        }

    assigned_plan = str(app.get("blinq_plan") or "").strip().lower()
    assigned_status = str(app.get("blinq_status") or "").strip().lower()
    expires_at = _parse_utc(app.get("blinq_expires_at"))

    if assigned_status == "suspended":
        return {
            "role": "user",
            "plan": assigned_plan if assigned_plan in PAID_PLANS else "expired",
            "plan_label": PLAN_LABELS.get(assigned_plan, PLAN_LABELS["expired"]),
            "status": "suspended",
            "expires_at": expires_at.isoformat() if expires_at else None,
            "trial_expires_at": trial_expires.isoformat() if trial_expires else None,
            "is_admin": False,
        }

    active_paid = assigned_plan in PAID_PLANS and assigned_status in {"active", "lifetime"}
    if active_paid and (assigned_status == "lifetime" or (expires_at is not None and expires_at > now)):
        return {
            "role": "user",
            "plan": assigned_plan,
            "plan_label": PLAN_LABELS[assigned_plan],
            "status": "lifetime" if assigned_status == "lifetime" else "active",
            "expires_at": expires_at.isoformat() if expires_at else None,
            "trial_expires_at": trial_expires.isoformat() if trial_expires else None,
            "is_admin": False,
        }

    if trial_expires and trial_expires > now and not assigned_plan:
        return {
            "role": "user",
            "plan": "rookie",
            "plan_label": "Rookie Trial",
            "status": "trial",
            "expires_at": trial_expires.isoformat(),
            "trial_expires_at": trial_expires.isoformat(),
            "is_admin": False,
        }

    return {
        "role": "user",
        "plan": assigned_plan if assigned_plan in PAID_PLANS else "expired",
        "plan_label": PLAN_LABELS.get(assigned_plan, PLAN_LABELS["expired"]),
        "status": "expired",
        "expires_at": expires_at.isoformat() if expires_at else None,
        "trial_expires_at": trial_expires.isoformat() if trial_expires else None,
        "is_admin": False,
    }


def public_account(user, *, cfg=None, now=None):
    metadata = user.get("user_metadata") or {}
    access = account_access(user, cfg=cfg, now=now)
    hide_ads_allowed = access.get("plan") in {"elite", "goat"} and access.get("status") in {"active", "lifetime"}
    hide_ads = bool(metadata.get("blinq_hide_ads")) and hide_ads_allowed
    return {
        "id": user["id"],
        "email": user.get("email", ""),
        "name": str(metadata.get("display_name") or metadata.get("name") or "Člen BlinQ")[:80],
        **access,
        "hide_ads_allowed": hide_ads_allowed,
        "hide_ads": hide_ads,
    }
