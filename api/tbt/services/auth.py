"""Identity and BlinQ account access helpers.

Firebase Auth is the primary identity provider. A narrow Supabase Auth fallback is
kept temporarily so the deployment can be rolled back without touching tennis
storage. Supabase must never be used for historical tennis data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock

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

_FIREBASE_APP = None
_FIREBASE_APP_LOCK = Lock()


def request_authorization(headers):
    """Return the user bearer token without trusting SWA's rewritten Authorization header."""
    custom = str(headers.get("X-Blinq-Access-Token") or "").strip()
    if custom:
        return custom if custom.lower().startswith("bearer ") else f"Bearer {custom}"
    return headers.get("Authorization")


def firebase_configured(cfg) -> bool:
    return bool(
        str(getattr(cfg, "firebase_project_id", "") or "").strip()
        and str(getattr(cfg, "firebase_client_email", "") or "").strip()
        and str(getattr(cfg, "firebase_private_key", "") or "").strip()
    )


def auth_provider(cfg) -> str:
    if firebase_configured(cfg):
        return "firebase"
    if str(getattr(cfg, "supabase_url", "") or "").strip() and str(
        getattr(cfg, "supabase_anon_key", "") or ""
    ).strip():
        return "supabase"
    return "none"


def _firebase_modules():
    try:
        import firebase_admin
        from firebase_admin import auth as firebase_auth
        from firebase_admin import credentials
    except ImportError as exc:  # pragma: no cover - production dependency guard
        raise AuthUnavailable("Firebase Admin SDK is not installed") from exc
    return firebase_admin, firebase_auth, credentials


def _normalized_private_key(cfg) -> str:
    value = str(getattr(cfg, "firebase_private_key", "") or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
        value = value[1:-1].strip()
    # Azure may store a PEM either with real newlines or escaped \n sequences.
    if "\\n" in value and "\n" not in value:
        value = value.replace("\\n", "\n")
    return value


def firebase_app(cfg):
    """Return a lazily initialized named Firebase Admin app."""
    global _FIREBASE_APP
    if _FIREBASE_APP is not None:
        return _FIREBASE_APP
    if not firebase_configured(cfg):
        raise AuthUnavailable("Firebase authentication is not configured")

    firebase_admin, _, credentials = _firebase_modules()
    with _FIREBASE_APP_LOCK:
        if _FIREBASE_APP is not None:
            return _FIREBASE_APP
        try:
            _FIREBASE_APP = firebase_admin.get_app("blinq")
            return _FIREBASE_APP
        except ValueError:
            pass

        info = {
            "type": "service_account",
            "project_id": str(cfg.firebase_project_id).strip(),
            "private_key": _normalized_private_key(cfg),
            "client_email": str(cfg.firebase_client_email).strip(),
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        try:
            credential = credentials.Certificate(info)
            _FIREBASE_APP = firebase_admin.initialize_app(
                credential,
                {"projectId": str(cfg.firebase_project_id).strip()},
                name="blinq",
            )
        except Exception as exc:  # key/config errors must not leak details
            raise AuthUnavailable("Firebase authentication is not configured correctly") from exc
    return _FIREBASE_APP


def _millis_iso(value):
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()


def firebase_user_to_dict(record) -> dict:
    """Normalize Firebase UserRecord to the internal Supabase-compatible shape."""
    claims = dict(getattr(record, "custom_claims", None) or {})
    metadata = getattr(record, "user_metadata", None)
    created_at = _millis_iso(getattr(metadata, "creation_timestamp", None))
    last_sign_in_at = _millis_iso(getattr(metadata, "last_sign_in_timestamp", None))
    display_name = str(getattr(record, "display_name", None) or "").strip()
    return {
        "id": str(getattr(record, "uid", "") or ""),
        "email": str(getattr(record, "email", None) or ""),
        "created_at": created_at,
        "last_sign_in_at": last_sign_in_at,
        "app_metadata": claims,
        "user_metadata": {
            "display_name": display_name,
            "name": display_name,
            "blinq_avatar_variant": claims.get("blinq_avatar_variant", ""),
            "blinq_hide_ads": bool(claims.get("blinq_hide_ads", False)),
        },
    }


def firebase_get_user(cfg, user_id):
    user_id = str(user_id or "").strip()
    if not user_id or len(user_id) > 256:
        raise ValueError("Invalid user id")
    _, firebase_auth, _ = _firebase_modules()
    try:
        record = firebase_auth.get_user(user_id, app=firebase_app(cfg))
        return firebase_user_to_dict(record)
    except Exception as exc:
        user_not_found = getattr(firebase_auth, "UserNotFoundError", None)
        if isinstance(user_not_found, type) and isinstance(exc, user_not_found):
            return None
        raise AuthUnavailable("Identity service temporarily unavailable") from exc


def _verify_firebase_user(token, cfg):
    _, firebase_auth, _ = _firebase_modules()
    try:
        decoded = firebase_auth.verify_id_token(token, app=firebase_app(cfg), check_revoked=True)
        user_id = str(decoded.get("uid") or decoded.get("sub") or "").strip()
        if not user_id:
            return None
        return firebase_get_user(cfg, user_id)
    except Exception as exc:
        invalid_names = (
            "InvalidIdTokenError",
            "ExpiredIdTokenError",
            "RevokedIdTokenError",
            "UserDisabledError",
            "UserNotFoundError",
        )
        invalid_types = tuple(
            value
            for value in (getattr(firebase_auth, name, None) for name in invalid_names)
            if isinstance(value, type)
        )
        if invalid_types and isinstance(exc, invalid_types):
            return None
        if isinstance(exc, ValueError):
            return None
        if isinstance(exc, AuthUnavailable):
            raise
        raise AuthUnavailable("Identity service temporarily unavailable") from exc


def _verify_supabase_user(token, cfg, client=None):
    if not cfg.supabase_url or not cfg.supabase_anon_key:
        raise AuthUnavailable("Authentication is not configured")
    own = client is None
    client = client or httpx.Client(timeout=10)
    try:
        response = client.get(
            f"{cfg.supabase_url}/auth/v1/user",
            headers={"apikey": cfg.supabase_anon_key, "Authorization": f"Bearer {token}"},
        )
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


def verify_user(authorization, cfg, client=None):
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if not token or len(token) > 16384:
        return None
    provider = auth_provider(cfg)
    if provider == "firebase":
        return _verify_firebase_user(token, cfg)
    if provider == "supabase":
        return _verify_supabase_user(token, cfg, client=client)
    raise AuthUnavailable("Authentication is not configured")


def update_firebase_profile(cfg, user_id, payload):
    """Update user-controlled presentation data without exposing custom claims."""
    if not firebase_configured(cfg):
        raise AuthUnavailable("Firebase authentication is not configured")
    if not isinstance(payload, dict):
        raise ValueError("Invalid profile update")
    user_id = str(user_id or "").strip()
    if not user_id:
        raise ValueError("Invalid user id")

    _, firebase_auth, _ = _firebase_modules()
    app = firebase_app(cfg)
    try:
        record = firebase_auth.get_user(user_id, app=app)
        claims = dict(record.custom_claims or {})

        if "display_name" in payload:
            display_name = str(payload.get("display_name") or "").strip()[:80]
            firebase_auth.update_user(user_id, display_name=display_name or None, app=app)

        if "blinq_avatar_variant" in payload:
            avatar = str(payload.get("blinq_avatar_variant") or "").strip().lower()
            claims["blinq_avatar_variant"] = avatar if avatar in {"m", "w"} else ""

        if "blinq_hide_ads" in payload:
            claims["blinq_hide_ads"] = bool(payload.get("blinq_hide_ads"))

        firebase_auth.set_custom_user_claims(user_id, claims or None, app=app)
        updated = firebase_auth.get_user(user_id, app=app)
        return firebase_user_to_dict(updated)
    except ValueError:
        raise
    except Exception as exc:
        raise AuthUnavailable("Identity service temporarily unavailable") from exc


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
    """Resolve role/plan state from admin-controlled metadata and signup time.

    Trial is derived, not stored: an account without active paid access gets 72 hours
    from the identity provider's immutable creation timestamp. Paid access remains
    server-controlled so a normal user cannot grant themselves a plan.
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
    hide_ads_allowed = access.get("plan") in {"elite", "legend", "goat"} and access.get("status") in {"active", "lifetime"}
    hide_ads = bool(metadata.get("blinq_hide_ads")) and hide_ads_allowed
    avatar_variant = str(metadata.get("blinq_avatar_variant") or "").strip().lower()
    if avatar_variant not in {"m", "w"}:
        avatar_variant = ""
    return {
        "id": user["id"],
        "email": user.get("email", ""),
        "name": str(metadata.get("display_name") or metadata.get("name") or "BlinQ Member")[:80],
        **access,
        "avatar_variant": avatar_variant,
        "hide_ads_allowed": hide_ads_allowed,
        "hide_ads": hide_ads,
    }
