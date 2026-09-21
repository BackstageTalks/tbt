"""Admin-only Firebase identity account management helpers.

This module manages identity/account metadata only and never tennis data.
"""
from __future__ import annotations

from datetime import datetime, timezone
import threading
import time


from .auth import (
    AuthUnavailable,
    PAID_PLANS,
    _firebase_modules,
    account_access,
    firebase_app,
    firebase_configured,
    firebase_get_user,
    firebase_user_to_dict,
    profile_claims,
)
from .account_storage import (
    load_account_metadata,
    record_access_audit,
    save_payment_reference,
)
from .admin_storage import AdminStorageUnavailable


ALLOWED_STATUSES = {"active", "expired", "suspended", "lifetime"}
ALLOWED_ROLES = {"user", "admin"}


def tg_private_state(account: dict, profile: dict | None = None) -> dict:
    """Return the manual Telegram Private operational state for an account."""
    profile = profile if isinstance(profile, dict) else {}
    member = bool(profile.get("tg_private_member", False))
    eligible = (
        str((account or {}).get("status") or "").lower() in {"active", "lifetime"}
        and str((account or {}).get("plan") or "").lower() in {"elite", "legend", "goat"}
    )
    if eligible and not member:
        action = "add"
    elif not eligible and member:
        action = "remove"
    elif eligible and member:
        action = "ok"
    else:
        action = "none"
    return {
        "tg_private_member": member,
        "tg_private_eligible": eligible,
        "tg_private_action": action,
    }



def mirror_admin_metadata_claims(cfg, user_id, payload):
    """Legacy compatibility shim; operational metadata no longer mutates claims.

    TG-private membership/admin metadata is not an authorization claim. Keeping
    it in the same Firebase custom-claims object as role/plan/status created a
    read-modify-write race that could restore stale access. Durable account
    metadata is authoritative; this helper only refreshes the identity record.
    """
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("Invalid user id")
    _, firebase_auth, _ = _firebase_modules()
    app = firebase_app(cfg)
    try:
        return firebase_user_to_dict(firebase_auth.get_user(uid, app=app))
    except ValueError:
        raise
    except Exception as exc:
        raise AuthUnavailable("Firebase admin service temporarily unavailable") from exc

_USER_PAGE_TOKEN_CACHE: dict[tuple[int, int], tuple[float, str | None]] = {}
_USER_PAGE_TOKEN_LOCK = threading.Lock()
_USER_PAGE_TOKEN_TTL = 600.0

def _cache_page_token(per_page: int, page: int, token: str | None) -> None:
    with _USER_PAGE_TOKEN_LOCK:
        _USER_PAGE_TOKEN_CACHE[(per_page, page)] = (time.monotonic(), token)

def _cached_page_token(per_page: int, page: int):
    with _USER_PAGE_TOKEN_LOCK:
        row = _USER_PAGE_TOKEN_CACHE.get((per_page, page))
        if not row:
            return False, None
        created, token = row
        if time.monotonic() - created > _USER_PAGE_TOKEN_TTL:
            _USER_PAGE_TOKEN_CACHE.pop((per_page, page), None)
            return False, None
        return True, token

def _firebase_list_users(cfg, *, page=1, per_page=100):
    """List one Firebase page without rescanning page 1 for every request.

    The Admin UI and account worker use numeric pages for compatibility. Firebase
    itself is cursor based, so cache page-start tokens for a short period and walk
    only from the nearest known cursor. On older/mocked SDKs that do not accept a
    page_token argument, fall back to the legacy get_next_page traversal.
    """
    _, firebase_auth, _ = _firebase_modules()
    app = firebase_app(cfg)
    page = max(1, int(page))
    try:
        # Page 1 always starts without a token. Later pages can reuse the token
        # learned by the immediately preceding page/request.
        start_page = 1
        token = None
        if page > 1:
            for candidate in range(page, 1, -1):
                found, cached = _cached_page_token(per_page, candidate)
                if found:
                    if cached is None:
                        return []
                    start_page, token = candidate, cached
                    break
        current = start_page
        while current <= page:
            kwargs = {"max_results": per_page, "app": app}
            if token:
                kwargs["page_token"] = token
            try:
                result = firebase_auth.list_users(**kwargs)
            except TypeError:
                # Compatibility path for test doubles/older SDK facades.
                result = firebase_auth.list_users(max_results=per_page, app=app)
                current = 1
                while result is not None and current < page:
                    result = result.get_next_page()
                    current += 1
                if result is None:
                    return []
                return [firebase_user_to_dict(record) for record in result.users]
            if result is None:
                _cache_page_token(per_page, current + 1, None)
                return []
            has_token_attr = hasattr(result, "next_page_token")
            next_token = getattr(result, "next_page_token", None)
            # Some SDK versions expose only get_next_page(). Numeric page callers
            # still work; token caching simply remains unavailable in that case.
            if current == page:
                if has_token_attr:
                    _cache_page_token(per_page, current + 1, str(next_token) if next_token else None)
                return [firebase_user_to_dict(record) for record in result.users]
            if has_token_attr and not next_token:
                _cache_page_token(per_page, current + 1, None)
                return []
            if not has_token_attr:
                nxt = result.get_next_page()
                if nxt is None:
                    _cache_page_token(per_page, current + 1, None)
                    return []
                result = nxt
                token = getattr(result, "next_page_token", None)
                current += 1
                if current == page:
                    return [firebase_user_to_dict(record) for record in result.users]
                # No reusable token exposed: continue legacy traversal from here.
                while result is not None and current < page:
                    result = result.get_next_page()
                    current += 1
                return [] if result is None else [firebase_user_to_dict(record) for record in result.users]
            token = str(next_token)
            _cache_page_token(per_page, current + 1, token)
            current += 1
        return []
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
    payment_reference_present = "payment_reference" in payload
    payment_reference = _clean_text(payload.get("payment_reference"), max_len=120)

    if role not in ALLOWED_ROLES:
        raise ValueError("Invalid role")
    if plan and plan not in PAID_PLANS:
        raise ValueError("Invalid plan")
    if status not in ALLOWED_STATUSES:
        raise ValueError("Invalid status")
    if status == "lifetime":
        raise ValueError("Lifetime membership is no longer assignable; use active with an expiration date")
    if status == "active" and not plan and role != "admin":
        raise ValueError("Active status requires a plan")
    if status == "active" and plan == "rookie":
        # ROOKIE is the permanent free base tier and never needs an expiry.
        expires_at = None
    elif status == "active" and plan and expires_at is None:
        raise ValueError("Active paid plan requires an expiration date")
    if role == "admin" and status not in {"active", "suspended"}:
        raise ValueError("Admin status must be active or suspended")

    return {
        "role": role,
        "plan": plan,
        "status": status,
        "expires_at": expires_at,
        "payment_reference": payment_reference,
        "payment_reference_present": payment_reference_present,
    }


def _apply_access_metadata(app, changes):
    """Return authorization-only Firebase custom claims.

    Payment references, actor ids and audit timestamps deliberately stay out of
    ID-token claims. Users can inspect their own tokens, and profile/admin claim
    writers must never race over unrelated data.
    """
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

    # Remove legacy non-authorization data from the next claim write.
    for key in (
        "blinq_payment_reference", "blinq_access_updated_at",
        "blinq_access_updated_by", "blinq_hide_ads",
    ):
        app.pop(key, None)
    return app


def _update_firebase_user_access(cfg, user_id, changes, *, actor_id=""):
    _, firebase_auth, _ = _firebase_modules()
    app = firebase_app(cfg)
    uid = str(user_id).strip()
    storage_warning = ""
    try:
        record = firebase_auth.get_user(uid, app=app)
        before_user = firebase_user_to_dict(record)
        before_access = account_access(before_user, cfg=cfg)

        previous_reference = ""
        storage_ready = True
        try:
            previous_meta = load_account_metadata(uid)
            previous_reference = previous_meta.get("payment_reference", "")
            intended_after = {
                **before_access,
                "role": changes["role"],
                "plan": changes["plan"] or ("admin" if changes["role"] == "admin" else "expired"),
                "status": changes["status"],
                "expires_at": changes["expires_at"],
            }
            record_access_audit(
                actor_id=actor_id, target_id=uid, before=before_access,
                after=intended_after, outcome="requested",
            )
            desired_reference = changes.get("payment_reference", "") if changes.get("payment_reference_present") else previous_reference
            save_payment_reference(uid, desired_reference, actor_id=actor_id)
        except AdminStorageUnavailable:
            # Core access management must remain available even when the optional
            # operational metadata store is down. Payment reference/audit are
            # skipped and clearly reported to the caller.
            storage_ready = False
            storage_warning = "operational_metadata_not_persisted"

        claims = _apply_access_metadata(record.custom_claims or {}, changes)
        try:
            firebase_auth.set_custom_user_claims(uid, claims, app=app)
        except Exception:
            if storage_ready:
                try:
                    save_payment_reference(uid, previous_reference, actor_id=actor_id)
                    record_access_audit(
                        actor_id=actor_id, target_id=uid, before=before_access,
                        after=before_access, outcome="failed",
                    )
                except Exception:
                    pass
            raise

        updated = firebase_auth.get_user(uid, app=app)
        updated_user = firebase_user_to_dict(updated)
        after_access = account_access(updated_user, cfg=cfg)
        if storage_ready:
            try:
                record_access_audit(
                    actor_id=actor_id, target_id=uid, before=before_access,
                    after=after_access, outcome="success",
                )
            except AdminStorageUnavailable:
                storage_warning = "audit_not_persisted"
        if storage_warning:
            updated_user["admin_storage_warning"] = storage_warning
        return updated_user
    except ValueError:
        raise
    except Exception as exc:
        if isinstance(exc, AuthUnavailable):
            raise
        raise AuthUnavailable("Firebase admin service temporarily unavailable") from exc



def update_user_identity(cfg, user_id, payload):
    """Admin-only update of Firebase identity fields.

    Membership stays separate from identity so an e-mail correction can never
    accidentally change a user's BlinQ access.
    """
    if not isinstance(payload, dict):
        raise ValueError("Invalid identity update")
    uid = str(user_id or "").strip()
    if not uid or len(uid) > 256:
        raise ValueError("Invalid user id")
    allowed = {"email", "display_name"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("Unsupported identity field")

    email = str(payload.get("email") or "").strip()
    display_name = str(payload.get("display_name") or "").strip()
    if "email" in payload:
        if not email or len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("Invalid e-mail")
    if len(display_name) > 80:
        raise ValueError("Display name is too long")

    _, firebase_auth, _ = _firebase_modules()
    app = firebase_app(cfg)
    kwargs = {}
    if "email" in payload:
        kwargs["email"] = email
    if "display_name" in payload:
        kwargs["display_name"] = display_name or None
    try:
        if kwargs:
            firebase_auth.update_user(uid, app=app, **kwargs)
        return firebase_user_to_dict(firebase_auth.get_user(uid, app=app))
    except ValueError:
        raise
    except Exception as exc:
        raise AuthUnavailable("Firebase admin service temporarily unavailable") from exc


def delete_user_account(cfg, user_id):
    """Delete a Firebase identity. Durable profile cleanup is handled by API layer."""
    uid = str(user_id or "").strip()
    if not uid or len(uid) > 256:
        raise ValueError("Invalid user id")
    _, firebase_auth, _ = _firebase_modules()
    app = firebase_app(cfg)
    try:
        firebase_auth.delete_user(uid, app=app)
        return True
    except ValueError:
        raise
    except Exception as exc:
        raise AuthUnavailable("Firebase admin service temporarily unavailable") from exc

def update_user_access(cfg, user_id, payload, *, actor_id="", client=None):
    changes = normalize_access_update(payload)
    if not firebase_configured(cfg):
        raise AuthUnavailable("Firebase admin account management is not configured")
    return _update_firebase_user_access(cfg, user_id, changes, actor_id=actor_id)
