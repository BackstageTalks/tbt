from pathlib import Path
from collections import defaultdict, deque
from threading import Lock
import hashlib
import logging
import json
import time

import azure.functions as func

from tbt.config import settings
from tbt.services.auth import (
    AuthUnavailable,
    auth_provider,
    is_admin,
    is_suspended,
    public_account,
    request_authorization,
    update_firebase_profile,
    verify_user,
)
from tbt.services.admin_accounts import list_users, update_user_access
from tbt.services.account_storage import (
    load_account_metadata,
    load_account_metadata_many,
    normalize_profile_update,
    save_profile_metadata,
)
from tbt.services.admin_storage import (
    AdminStorageUnavailable,
    banner_analytics_summary,
    load_runtime_ui_config,
    record_banner_event,
    save_runtime_ui_config,
)
from tbt.services.content_news import news_pool
from tbt.services.feed import read_feed, visible_feed
from tbt.services.entitlements import filter_feed_for_access

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
FEED = Path(__file__).parent / "data/feed.json"
RELEASE = "6.5.46"
API_VERSION = "3.5.1"

# Lightweight abuse guard for the anonymous banner telemetry endpoint. This is intentionally
# instance-local: durable analytics remains in Table Storage, while this only absorbs accidental
# loops / trivial floods without keeping raw client identifiers in memory.
_BANNER_RATE_WINDOW_SECONDS = 60.0
_BANNER_RATE_MAX_EVENTS = 60
_BANNER_RATE_GLOBAL_MAX_EVENTS = 600
_BANNER_RATE_BUCKETS = defaultdict(deque)
_BANNER_RATE_GLOBAL = deque()
_BANNER_RATE_LOCK = Lock()


def _banner_event_allowed(payload):
    client_id = str((payload or {}).get("client_id") or "anonymous")[:256]
    key = hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:24]
    now = time.monotonic()
    cutoff = now - _BANNER_RATE_WINDOW_SECONDS
    with _BANNER_RATE_LOCK:
        while _BANNER_RATE_GLOBAL and _BANNER_RATE_GLOBAL[0] < cutoff:
            _BANNER_RATE_GLOBAL.popleft()
        if len(_BANNER_RATE_GLOBAL) >= _BANNER_RATE_GLOBAL_MAX_EVENTS:
            return False
        bucket = _BANNER_RATE_BUCKETS[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _BANNER_RATE_MAX_EVENTS:
            return False
        bucket.append(now)
        _BANNER_RATE_GLOBAL.append(now)
        # Keep this best-effort guard bounded on a long-running worker.
        if len(_BANNER_RATE_BUCKETS) > 10000:
            stale = [k for k, values in list(_BANNER_RATE_BUCKETS.items())[:2000] if not values or values[-1] < cutoff]
            for stale_key in stale:
                _BANNER_RATE_BUCKETS.pop(stale_key, None)
    return True


def response(payload, status=200):
    return func.HttpResponse(
        json.dumps(payload, ensure_ascii=False, allow_nan=False),
        status_code=status,
        mimetype="application/json",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-BlinQ-Release": RELEASE},
    )


def _verified_user(req):
    return verify_user(request_authorization(req.headers), settings)


def _profile_for(user, *, required=False):
    if not user:
        return {}
    try:
        return load_account_metadata(user.get("id"))
    except AdminStorageUnavailable:
        if required:
            raise
        logging.exception("Account metadata storage unavailable")
        return {}


def _admin_user(req):
    user = _verified_user(req)
    if not user:
        return None, response({"error": "unauthorized"}, 401)
    if not bool(user.get("email_verified", False)):
        return None, response({"error": "email_not_verified"}, 403)
    if is_suspended(user):
        return None, response({"error": "account_suspended"}, 403)
    if not is_admin(user, settings):
        return None, response({"error": "forbidden"}, 403)
    return user, None


def _admin_account_row(user, profile=None):
    profile = profile if isinstance(profile, dict) else _profile_for(user, required=True)
    account = public_account(user, cfg=settings, profile=profile)
    return {
        **account,
        "created_at": user.get("created_at"),
        "last_sign_in_at": user.get("last_sign_in_at"),
        "payment_reference": str(profile.get("payment_reference") or "")[:120],
    }


@app.route(route="health", methods=["GET"])
def health(req):
    return response({"ok": True, "version": API_VERSION, "release": RELEASE, "auth": auth_provider(settings)})


@app.route(route="v1/auth/config", methods=["GET"])
def auth_config(req):
    provider = auth_provider(settings)
    payload = {"enabled": provider != "none", "provider": provider, "release": RELEASE}
    if provider == "firebase":
        payload.update({
            "project_id": settings.firebase_project_id,
            "auth_domain": f"{settings.firebase_project_id}.firebaseapp.com",
        })
    return response(payload)


@app.route(route="v1/auth/me", methods=["GET"])
def account(req):
    try:
        user = _verified_user(req)
        return response(public_account(user, cfg=settings, profile=_profile_for(user))) if user else response({"error": "unauthorized"}, 401)
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)


@app.route(route="v1/auth/profile", methods=["PUT"])
def auth_profile(req):
    try:
        user = _verified_user(req)
        if not user:
            return response({"error": "unauthorized"}, 401)
        if not bool(user.get("email_verified", False)):
            return response({"error": "email_not_verified"}, 403)
        if is_suspended(user):
            return response({"error": "account_suspended"}, 403)
        if auth_provider(settings) != "firebase":
            return response({"error": "profile_update_unavailable"}, 503)
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        normalized = normalize_profile_update(payload)
        firebase_payload = {}
        if isinstance(payload, dict) and "display_name" in payload:
            firebase_payload["display_name"] = normalized["display_name"]
        updated = update_firebase_profile(settings, user.get("id"), firebase_payload)
        profile = save_profile_metadata(user.get("id"), payload)
        return response(public_account(updated, cfg=settings, profile=profile))
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"error": "account_storage_unavailable"}, 503)


@app.route(route="v1/ui-config", methods=["GET"])
def runtime_ui_config(req):
    try:
        config = load_runtime_ui_config()
        return response({"configured": bool(config), "config": config})
    except AdminStorageUnavailable:
        return response({"error": "ui_config_storage_unavailable", "configured": False, "config": None, "storage_available": False}, 503)


@app.route(route="v1/content/news", methods=["GET"])
def content_news(req):
    try:
        runtime = None
        try:
            runtime = load_runtime_ui_config()
        except AdminStorageUnavailable:
            runtime = None
        return response(news_pool(config=runtime))
    except (ValueError, OSError, TypeError):
        logging.exception("RSS/news content unavailable")
        return response({"items": [], "sources": 0, "error": "news_unavailable"}, 503)


@app.route(route="v1/banner-events", methods=["POST"])
def banner_events(req):
    try:
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        if not isinstance(payload, dict):
            return response({"error": "invalid_analytics_event"}, 400)
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 4096:
            return response({"error": "analytics_event_too_large"}, 413)
        if not _banner_event_allowed(payload):
            return response({"error": "rate_limited"}, 429)
        record_banner_event(payload)
        return response({"accepted": True}, 202)
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AdminStorageUnavailable:
        return response({"error": "analytics_storage_unavailable"}, 503)


@app.route(route="v1/feed", methods=["GET"])
def feed(req):
    try:
        user = _verified_user(req)
        if not user:
            return response({"error": "unauthorized"}, 401)
        if not bool(user.get("email_verified", False)):
            return response({"error": "email_not_verified"}, 403)
        account_data = public_account(user, cfg=settings, profile=_profile_for(user))
        data = visible_feed(read_feed(FEED))
        try:
            
            try:
                runtime_ui = load_runtime_ui_config()
            except AdminStorageUnavailable:
                runtime_ui = None
            data, entitlements = filter_feed_for_access(data, account_data, runtime_ui)
        except PermissionError:
            return response({"error": "account_suspended"}, 403)
        data["account"] = account_data
        data["entitlements"] = entitlements
        return response(data)
    except AuthUnavailable:
        return response({"error": "auth_unavailable"}, 503)
    except (ValueError, OSError, KeyError, TypeError):
        logging.exception("Serving feed unavailable")
        return response({"error": "feed_unavailable"}, 503)


@app.route(route="v1/admin/users", methods=["GET"])
def admin_users(req):
    try:
        actor, denied = _admin_user(req)
        if denied:
            return denied
        try:
            page = max(1, int(req.params.get("page") or 1))
            per_page = max(1, min(200, int(req.params.get("per_page") or 100)))
        except (TypeError, ValueError):
            return response({"error": "invalid_pagination"}, 400)
        users = list_users(settings, page=page, per_page=per_page)
        profiles = load_account_metadata_many([user.get("id") for user in users])
        return response({
            "users": [_admin_account_row(user, profiles.get(str(user.get("id") or ""), {})) for user in users],
            "page": page,
            "per_page": per_page,
            "actor_id": actor.get("id"),
        })
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"error": "admin_storage_unavailable"}, 503)
    except (ValueError, TypeError):
        logging.exception("Admin user listing failed")
        return response({"error": "admin_users_unavailable"}, 503)


@app.route(route="v1/admin/users/{user_id}/access", methods=["PUT"])
def admin_user_access(req):
    try:
        actor, denied = _admin_user(req)
        if denied:
            return denied
        user_id = str((req.route_params or {}).get("user_id") or "").strip()
        if not user_id:
            return response({"error": "invalid_user_id"}, 400)
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        if user_id == str(actor.get("id")):
            requested_role = str((payload or {}).get("role") or "user").strip().lower()
            requested_status = str((payload or {}).get("status") or "expired").strip().lower()
            if requested_role != "admin" or requested_status == "suspended":
                return response({"error": "cannot_disable_own_admin_access"}, 409)
        updated = update_user_access(
            settings,
            user_id,
            payload,
            actor_id=str(actor.get("id") or ""),
        )
        return response(_admin_account_row(updated))
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"error": "admin_storage_unavailable"}, 503)
    except (TypeError, KeyError):
        logging.exception("Admin access update failed")
        return response({"error": "admin_update_unavailable"}, 503)

@app.route(route="v1/admin/ui-config", methods=["PUT"])
def admin_ui_config(req):
    try:
        actor, denied = _admin_user(req)
        if denied:
            return denied
        try:
            payload = req.get_json()
        except ValueError:
            return response({"error": "invalid_json"}, 400)
        saved = save_runtime_ui_config(payload, actor_id=str(actor.get("id") or ""))
        return response(saved)
    except ValueError as exc:
        return response({"error": str(exc)}, 400)
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"error": "admin_storage_unavailable"}, 503)


@app.route(route="v1/admin/banner-analytics", methods=["GET"])
def admin_banner_analytics(req):
    try:
        _, denied = _admin_user(req)
        if denied:
            return denied
        try:
            days = int(req.params.get("days") or 30)
        except (TypeError, ValueError):
            return response({"error": "invalid_days"}, 400)
        return response(banner_analytics_summary(days=days))
    except AuthUnavailable:
        return response({"error": "admin_auth_unavailable"}, 503)
    except AdminStorageUnavailable:
        return response({"available": False, "error": "admin_storage_unavailable"}, 503)

