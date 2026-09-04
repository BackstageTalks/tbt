from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import azure.functions as func
import httpx

from tbt.config import settings
from tbt.log import configure_logging
from tbt.repositories.supabase import SupabaseRepository
from tbt.services.contracts import blinq_flat_prediction, public_prediction
from tbt.services.prime import prime_predictions

configure_logging()
logger = logging.getLogger("tbt.function_app")
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def _json(data: Any, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(data, ensure_ascii=False, default=str),
        status_code=status,
        mimetype="application/json",
        headers={
            "Access-Control-Allow-Origin": settings.cors_origins,
            "Cache-Control": "no-store",
            "X-TBT-Version": "v200",
        },
    )


AUTH_PLANS = {"free", "pro", "elite", "legend", "goat", "admin"}

def _bearer_token(req: func.HttpRequest) -> str:
    value = str(req.headers.get("Authorization") or "").strip()
    if not value.lower().startswith("bearer "):
        return ""
    return value.split(" ", 1)[1].strip()

def _verify_supabase_user(req: func.HttpRequest) -> dict[str, Any] | None:
    token = _bearer_token(req)
    if not token or not settings.supabase_url or not settings.supabase_anon_key:
        return None
    url = f"{str(settings.supabase_url).rstrip('/')}/auth/v1/user"
    response = httpx.get(
        url,
        headers={
            "apikey": settings.supabase_anon_key,
            "Authorization": f"Bearer {token}",
        },
        timeout=15.0,
    )
    if response.status_code in {401, 403}:
        return None
    if response.is_error:
        raise RuntimeError(f"Supabase Auth verification failed: HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    return data if isinstance(data, dict) and data.get("id") else None

def _auth_provider(user: dict[str, Any]) -> str:
    app_meta = user.get("app_metadata") if isinstance(user.get("app_metadata"), dict) else {}
    provider = str(app_meta.get("provider") or "").strip()
    return provider or "email"


def _identity_metadata(user: dict[str, Any]) -> dict[str, Any]:
    metadata = user.get("user_metadata") if isinstance(user.get("user_metadata"), dict) else {}
    identities = user.get("identities") if isinstance(user.get("identities"), list) else []
    provider = _auth_provider(user)
    if provider.startswith("custom:telegram"):
        for identity in identities:
            if isinstance(identity, dict) and str(identity.get("provider") or "") == provider:
                identity_data = identity.get("identity_data") if isinstance(identity.get("identity_data"), dict) else {}
                return {**identity_data, **metadata}
    return metadata


def _default_profile(user: dict[str, Any]) -> dict[str, Any]:
    email = str(user.get("email") or "")
    metadata = _identity_metadata(user)
    name = str(metadata.get("display_name") or metadata.get("name") or metadata.get("preferred_username") or email.split("@", 1)[0] or "BlinQ User").strip()
    provider = _auth_provider(user)
    tg_handle = str(metadata.get("preferred_username") or metadata.get("username") or "").strip() if provider.startswith("custom:telegram") else ""
    tg_id = str(metadata.get("id") or metadata.get("sub") or "").strip() if provider.startswith("custom:telegram") else ""
    return {
        "id": str(user.get("id") or ""),
        "email": email,
        "display_name": name[:80] or "BlinQ User",
        "plan": "free",
        "plan_label": "Free",
        "entitlement_expires_at": None,
        "avatar_variant": "a",
        "avatar_url": "",
        "auth_provider": provider,
        "telegram_id": tg_id,
        "telegram_handle": tg_handle,
        "telegram_photo_url": str(metadata.get("picture") or metadata.get("photo_url") or "") if provider.startswith("custom:telegram") else "",
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

def _profile_for_user(repo: SupabaseRepository, user: dict[str, Any]) -> dict[str, Any]:
    user_id = str(user.get("id") or "")
    rows = repo.select_all(
        "user_profiles",
        filters={"id": f"eq.{user_id}"},
        max_rows=1,
        page_size=1,
    )
    if rows:
        row = dict(rows[0])
    else:
        row = _default_profile(user)
    metadata = _identity_metadata(user)
    provider = _auth_provider(user)
    row["auth_provider"] = provider
    metadata_handle = str(metadata.get("telegram_handle") or metadata.get("preferred_username") or metadata.get("username") or "").strip().lstrip("@")
    if provider.startswith("custom:telegram"):
        row["telegram_id"] = str(metadata.get("id") or metadata.get("sub") or row.get("telegram_id") or "")
        row["telegram_handle"] = str(metadata.get("preferred_username") or metadata.get("username") or row.get("telegram_handle") or "")
        row["telegram_photo_url"] = str(metadata.get("picture") or metadata.get("photo_url") or row.get("telegram_photo_url") or "")
        if not str(row.get("display_name") or "").strip() or str(row.get("display_name")) == "BlinQ User":
            row["display_name"] = str(metadata.get("name") or metadata.get("preferred_username") or "BlinQ User")[:80]
    elif metadata_handle:
        row["telegram_handle"] = metadata_handle[:64]
        if not str(row.get("display_name") or "").strip() or str(row.get("display_name")) == "BlinQ User":
            row["display_name"] = f"@{metadata_handle[:63]}"
    try:
        repo.upsert("user_profiles", [row], "id")
    except Exception:
        logger.warning("Unable to persist/sync user profile for %s", user_id, exc_info=True)
    return row



def _telegram_handle(user: dict[str, Any], profile: dict[str, Any]) -> str:
    explicit = str(profile.get("telegram_handle") or "").strip()
    provider = str(profile.get("auth_provider") or _auth_provider(user) or "")
    metadata = _identity_metadata(user)
    if not explicit and provider.startswith("custom:telegram"):
        explicit = str(metadata.get("preferred_username") or metadata.get("username") or "").strip()
    if explicit:
        return explicit if explicit.startswith("@") else f"@{explicit}"
    telegram_id = str(profile.get("telegram_id") or metadata.get("id") or "").strip() if provider.startswith("custom:telegram") else ""
    return f"Telegram #{telegram_id}" if telegram_id else ""


def _account_contract(user: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    plan = str(profile.get("plan") or "free").lower()
    if plan not in AUTH_PLANS:
        plan = "free"
    expires_raw = profile.get("entitlement_expires_at")
    expires = None
    if expires_raw:
        try:
            expires = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
        except ValueError:
            expires = None
    expired = bool(expires and expires <= now and plan not in {"free", "admin"})
    effective_plan = "free" if expired else plan
    days_left = max(0, (expires - now).days + 1) if expires and expires > now else None
    label = str(profile.get("plan_label") or effective_plan.upper())
    entitlement = f"{days_left} days left" if days_left is not None else ("Expired · Free access" if expired else ("Active" if effective_plan != "free" else "Free"))
    return {
        "id": str(user.get("id") or profile.get("id") or ""),
        "email": str(user.get("email") or profile.get("email") or ""),
        "name": str(profile.get("display_name") or "BlinQ User"),
        "plan": effective_plan,
        "stored_plan": plan,
        "planLabel": label if not expired else "Free",
        "entitlement": entitlement,
        "entitlement_expires_at": expires_raw,
        "avatarVariant": str(profile.get("avatar_variant") or "a"),
        "avatarUrl": str(profile.get("avatar_url") or ""),
        "tgHandle": _telegram_handle(user, profile),
        "authProvider": str(profile.get("auth_provider") or _auth_provider(user)),
        "telegramPhotoUrl": str(profile.get("telegram_photo_url") or ""),
        "is_active": bool(profile.get("is_active", True)),
        "expired": expired,
        "authenticated": True,
    }


def _admin_authorized(req: func.HttpRequest) -> bool:
    configured = str(settings.admin_api_key or "").strip()
    provided = str(req.headers.get("x-admin-key") or "").strip()
    return bool(configured and provided and provided == configured)


def _read_ui_config(repo: SupabaseRepository) -> dict[str, Any] | None:
    rows = repo.select_all(
        "app_settings",
        filters={"setting_key": "eq.ui_config"},
        max_rows=1,
        page_size=1,
    )
    if not rows:
        return None
    value = rows[0].get("value")
    return value if isinstance(value, dict) else None


def _write_ui_config(repo: SupabaseRepository, value: dict[str, Any]) -> None:
    repo.upsert(
        "app_settings",
        [{
            "setting_key": "ui_config",
            "value": value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }],
        "setting_key",
    )


def _authenticated_account(req: func.HttpRequest, repo: SupabaseRepository | None = None) -> dict[str, Any] | None:
    user = _verify_supabase_user(req)
    if not user:
        return None
    repository = repo or SupabaseRepository()
    profile = _profile_for_user(repository, user)
    account = _account_contract(user, profile)
    return account if account.get("is_active") else None


def _feature_allowed(repo: SupabaseRepository, account: dict[str, Any], feature_id: str) -> bool:
    plan = str(account.get("plan") or "free").lower()
    if plan == "admin":
        return True
    config = _read_ui_config(repo) or {}
    access = config.get("access_control") if isinstance(config.get("access_control"), dict) else {}
    entries = access.get("entries") if isinstance(access.get("entries"), dict) else {}
    entry = entries.get(feature_id) if isinstance(entries.get(feature_id), dict) else None
    if not entry:
        return True
    allowed = entry.get("allowed_plans") if isinstance(entry.get("allowed_plans"), list) else []
    return plan in {str(value).lower() for value in allowed}


def _prediction_status(repo: SupabaseRepository) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    future = repo.select_all(
        "current_predictions",
        filters={"scheduled_at": f"gte.{now.isoformat()}"},
        order="scheduled_at.asc",
        max_rows=5000,
        page_size=1000,
    )
    latest_rows = repo.select_all(
        "current_predictions",
        order="scheduled_at.desc",
        max_rows=1,
        page_size=1,
    )
    latest = latest_rows[0] if latest_rows else {}
    generated_values = [row.get("generated_at") for row in future if row.get("generated_at")]
    if latest.get("generated_at"):
        generated_values.append(latest.get("generated_at"))
    return {
        "future_count": len(future),
        "next_match_at": future[0].get("scheduled_at") if future else None,
        "latest_scheduled_at": latest.get("scheduled_at"),
        "latest_generated_at": max(generated_values) if generated_values else None,
    }


@app.route(route="v1/auth/config", methods=["GET"])
def auth_config(req: func.HttpRequest) -> func.HttpResponse:
    enabled = bool(settings.supabase_url and settings.supabase_anon_key)
    telegram_enabled = str(os.getenv("TBT_TELEGRAM_AUTH_ENABLED", "")).strip().lower() in {"1", "true", "yes", "on"}
    telegram_provider = str(os.getenv("TBT_TELEGRAM_AUTH_PROVIDER", "custom:telegram") or "custom:telegram").strip()
    return _json({
        "success": True,
        "enabled": enabled,
        "required": True,
        "provider": "supabase",
        "supabase_url": settings.supabase_url if enabled else "",
        "anon_key": settings.supabase_anon_key if enabled else "",
        "telegram_enabled": bool(enabled and telegram_enabled),
        "telegram_provider": telegram_provider if enabled and telegram_enabled else "",
    })

@app.route(route="v1/auth/me", methods=["GET"])
def auth_me(req: func.HttpRequest) -> func.HttpResponse:
    try:
        user = _verify_supabase_user(req)
        if not user:
            return _json({"success": False, "error": "unauthorized"}, 401)
        profile = _profile_for_user(SupabaseRepository(), user)
        account = _account_contract(user, profile)
        if not account["is_active"]:
            return _json({"success": False, "error": "account_disabled"}, 403)
        return _json({"success": True, "account": account})
    except Exception as exc:
        logger.exception("auth_me failed")
        return _json({"success": False, "error": str(exc)}, 500)

@app.route(route="v1/auth/profile", methods=["POST"])
def auth_profile(req: func.HttpRequest) -> func.HttpResponse:
    try:
        user = _verify_supabase_user(req)
        if not user:
            return _json({"success": False, "error": "unauthorized"}, 401)
        payload = req.get_json()
        if not isinstance(payload, dict):
            return _json({"success": False, "error": "JSON object required"}, 400)
        repo = SupabaseRepository()
        row = _profile_for_user(repo, user)
        if "display_name" in payload:
            value = str(payload.get("display_name") or "").strip()[:80]
            if value:
                row["display_name"] = value
        if "avatar_variant" in payload:
            row["avatar_variant"] = "b" if str(payload.get("avatar_variant")).lower() == "b" else "a"
        if "avatar_url" in payload:
            row["avatar_url"] = str(payload.get("avatar_url") or "").strip()[:500]
        row["email"] = str(user.get("email") or row.get("email") or "")
        row["updated_at"] = datetime.now(timezone.utc).isoformat()
        repo.upsert("user_profiles", [row], "id")
        return _json({"success": True, "account": _account_contract(user, row)})
    except ValueError:
        return _json({"success": False, "error": "invalid JSON"}, 400)
    except Exception as exc:
        logger.exception("auth_profile failed")
        return _json({"success": False, "error": str(exc)}, 500)

@app.route(route="v1/admin/users", methods=["GET"])
def admin_users(req: func.HttpRequest) -> func.HttpResponse:
    if not _admin_authorized(req):
        return _json({"success": False, "error": "unauthorized"}, 401)
    try:
        rows = SupabaseRepository().select_all(
            "user_profiles",
            order="created_at.desc",
            max_rows=5000,
            page_size=500,
        )
        safe = [{
            "id": row.get("id"),
            "email": row.get("email"),
            "display_name": row.get("display_name"),
            "plan": row.get("plan"),
            "plan_label": row.get("plan_label"),
            "entitlement_expires_at": row.get("entitlement_expires_at"),
            "avatar_variant": row.get("avatar_variant"),
            "avatar_url": row.get("avatar_url"),
            "auth_provider": row.get("auth_provider"),
            "telegram_id": row.get("telegram_id"),
            "telegram_handle": row.get("telegram_handle"),
            "telegram_photo_url": row.get("telegram_photo_url"),
            "is_active": row.get("is_active"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        } for row in rows]
        return _json({"success": True, "count": len(safe), "users": safe})
    except Exception as exc:
        logger.exception("admin_users failed")
        return _json({"success": False, "error": str(exc)}, 500)

@app.route(route="v1/admin/users/{user_id}", methods=["POST"])
def admin_user_update(req: func.HttpRequest) -> func.HttpResponse:
    if not _admin_authorized(req):
        return _json({"success": False, "error": "unauthorized"}, 401)
    try:
        user_id = str(req.route_params.get("user_id") or "").strip()
        payload = req.get_json()
        if not user_id or not isinstance(payload, dict):
            return _json({"success": False, "error": "user id and JSON object required"}, 400)
        repo = SupabaseRepository()
        rows = repo.select_all("user_profiles", filters={"id": f"eq.{user_id}"}, max_rows=1, page_size=1)
        if not rows:
            return _json({"success": False, "error": "user_not_found"}, 404)
        row = dict(rows[0])
        if "plan" in payload:
            plan = str(payload.get("plan") or "free").lower()
            if plan not in AUTH_PLANS:
                return _json({"success": False, "error": "invalid_plan"}, 400)
            row["plan"] = plan
        if "plan_label" in payload:
            row["plan_label"] = str(payload.get("plan_label") or "").strip()[:80] or str(row.get("plan") or "free").upper()
        if "display_name" in payload:
            value = str(payload.get("display_name") or "").strip()[:80]
            if value:
                row["display_name"] = value
        if "avatar_url" in payload:
            row["avatar_url"] = str(payload.get("avatar_url") or "").strip()[:500]
        if "entitlement_expires_at" in payload:
            row["entitlement_expires_at"] = payload.get("entitlement_expires_at") or None
        if "is_active" in payload:
            row["is_active"] = bool(payload.get("is_active"))
        row["updated_at"] = datetime.now(timezone.utc).isoformat()
        repo.upsert("user_profiles", [row], "id")
        return _json({"success": True, "user": row})
    except ValueError:
        return _json({"success": False, "error": "invalid JSON"}, 400)
    except Exception as exc:
        logger.exception("admin_user_update failed")
        return _json({"success": False, "error": str(exc)}, 500)


@app.route(route="v1/predictions/status", methods=["GET"])
def predictions_status(req: func.HttpRequest) -> func.HttpResponse:
    try:
        repo = SupabaseRepository()
        if not _authenticated_account(req, repo):
            return _json({"success": False, "error": "unauthorized"}, 401)
        status = _prediction_status(repo)
        return _json({"success": True, **status})
    except Exception as exc:
        logger.exception("predictions_status failed")
        return _json({"success": False, "error": str(exc)}, 500)


@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _json(
        {
            "ok": True,
            "service": "TBT v200",
            "utc": datetime.now(timezone.utc).isoformat(),
            "inference_mode": "offline-github-actions",
            "supabase_configured": bool(
                settings.supabase_url and settings.supabase_anon_key
            ),
        }
    )




@app.route(route="v1/admin/avatar-upload", methods=["POST"])
def admin_avatar_upload(req: func.HttpRequest) -> func.HttpResponse:
    if not _admin_authorized(req):
        return _json({"success": False, "error": "unauthorized"}, 401)
    try:
        payload = req.get_json()
        if not isinstance(payload, dict):
            return _json({"success": False, "error": "JSON object required"}, 400)
        plan = str(payload.get("plan") or "custom").lower()
        if plan not in {"free", "pro", "elite", "legend", "goat", "custom"}:
            return _json({"success": False, "error": "invalid_plan"}, 400)
        content_type = str(payload.get("content_type") or "").lower()
        allowed = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
        if content_type not in allowed:
            return _json({"success": False, "error": "unsupported_image_type"}, 400)
        encoded = str(payload.get("data_base64") or "")
        try:
            body = base64.b64decode(encoded, validate=True)
        except Exception:
            return _json({"success": False, "error": "invalid_base64"}, 400)
        if not body or len(body) > 1_500_000:
            return _json({"success": False, "error": "avatar_too_large", "max_bytes": 1500000}, 413)
        original = str(payload.get("filename") or f"avatar{allowed[content_type]}")
        stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", original.rsplit(".", 1)[0]).strip("-")[:50] or "avatar"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        object_path = f"avatars/{plan}/{stamp}-{stem}{allowed[content_type]}"
        service_key = str(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "") or "").strip()
        supabase_url = str(settings.supabase_url or "").rstrip("/")
        if not supabase_url or not service_key:
            return _json({"success": False, "error": "storage_not_configured"}, 500)
        bucket = "blinq-assets"
        upload_url = f"{supabase_url}/storage/v1/object/{quote(bucket, safe='')}/{quote(object_path, safe='/')}"
        response = httpx.post(upload_url, content=body, headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": content_type,
            "x-upsert": "true",
        }, timeout=30.0)
        if response.is_error:
            raise RuntimeError(f"Storage upload failed: HTTP {response.status_code}: {response.text[:300]}")
        public_url = f"{supabase_url}/storage/v1/object/public/{quote(bucket, safe='')}/{quote(object_path, safe='/')}"
        return _json({"success": True, "url": public_url, "path": object_path, "bytes": len(body), "content_type": content_type})
    except ValueError:
        return _json({"success": False, "error": "invalid JSON"}, 400)
    except Exception as exc:
        logger.exception("admin_avatar_upload failed")
        return _json({"success": False, "error": str(exc)}, 500)


@app.route(route="v1/predictions/upcoming", methods=["GET"])
def predictions_upcoming(req: func.HttpRequest) -> func.HttpResponse:
    try:
        repo = SupabaseRepository()
        if not _authenticated_account(req, repo):
            return _json({"success": False, "error": "unauthorized"}, 401)
        days = max(
            1,
            min(int(req.params.get("days", settings.prediction_horizon_days)), 14),
        )
        tour = req.params.get("tour")
        if tour and tour.lower() not in {"atp", "wta"}:
            return _json({"error": "tour must be ATP or WTA"}, 400)

        now = datetime.now(timezone.utc) - timedelta(hours=6)
        end = now + timedelta(days=days)
        rows = repo.list_predictions(now, end, tour=tour)
        data = [public_prediction(row) for row in rows]

        return _json(
            {
                "success": True,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "count": len(data),
                "matches": data,
            }
        )
    except Exception as exc:
        logger.exception("predictions_upcoming failed")
        return _json({"success": False, "error": str(exc)}, 500)


@app.route(route="v1/predictions/prime", methods=["GET"])
def predictions_prime(req: func.HttpRequest) -> func.HttpResponse:
    try:
        repo = SupabaseRepository()
        account = _authenticated_account(req, repo)
        if not account:
            return _json({"success": False, "error": "unauthorized"}, 401)
        if not _feature_allowed(repo, account, "route.prime_picks"):
            return _json({"success": False, "error": "plan_required"}, 403)
        days = max(
            1,
            min(int(req.params.get("days", settings.prediction_horizon_days)), 14),
        )
        limit = max(1, min(int(req.params.get("limit", 10)), 20))
        tour = req.params.get("tour")
        if tour and tour.lower() not in {"atp", "wta"}:
            return _json({"error": "tour must be ATP or WTA"}, 400)

        minimum_score_raw = req.params.get("minimum_score")
        minimum_score = (
            float(minimum_score_raw)
            if minimum_score_raw not in (None, "")
            else None
        )

        now = datetime.now(timezone.utc) - timedelta(hours=6)
        end = now + timedelta(days=days)
        rows = repo.list_predictions(now, end, tour=tour)
        ranked = prime_predictions(
            rows,
            limit=limit,
            minimum_score=minimum_score,
        )
        data = [public_prediction(row) for row in ranked]

        return _json(
            {
                "success": True,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "count": len(data),
                "matches": data,
                "ranking": "calibrated_model_probability_desc",
            }
        )
    except Exception as exc:
        logger.exception("predictions_prime failed")
        return _json({"success": False, "error": str(exc)}, 500)


@app.route(route="blinq/predictions", methods=["GET"])
def blinq_predictions(req: func.HttpRequest) -> func.HttpResponse:
    try:
        days = max(
            1,
            min(int(req.params.get("days", settings.prediction_horizon_days)), 14),
        )
        now = datetime.now(timezone.utc) - timedelta(hours=6)
        rows = SupabaseRepository().list_predictions(
            now, now + timedelta(days=days)
        )
        return _json(
            {
                "success": True,
                "source": "TBT-v200",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "data": [blinq_flat_prediction(row) for row in rows],
            }
        )
    except Exception as exc:
        logger.exception("blinq_predictions failed")
        return _json({"success": False, "error": str(exc), "data": []}, 500)


@app.route(route="v1/ui-config", methods=["GET"])
def ui_config(req: func.HttpRequest) -> func.HttpResponse:
    try:
        config = _read_ui_config(SupabaseRepository())
        return _json({"success": True, "config": config})
    except Exception as exc:
        logger.exception("ui_config failed")
        return _json({"success": False, "config": None, "error": str(exc)}, 500)


@app.route(route="v1/admin/session", methods=["GET"])
def admin_session(req: func.HttpRequest) -> func.HttpResponse:
    if not _admin_authorized(req):
        return _json({"success": False, "error": "unauthorized"}, 401)
    return _json({"success": True, "admin": True})


@app.route(route="v1/admin/ui-config", methods=["POST"])
def admin_ui_config(req: func.HttpRequest) -> func.HttpResponse:
    if not _admin_authorized(req):
        return _json({"success": False, "error": "unauthorized"}, 401)
    try:
        raw = req.get_body()
        if len(raw) > 300_000:
            return _json({"success": False, "error": "config payload too large"}, 413)
        payload = req.get_json()
        if not isinstance(payload, dict):
            return _json({"success": False, "error": "JSON object required"}, 400)
        _write_ui_config(SupabaseRepository(), payload)
        return _json({"success": True, "saved_at": datetime.now(timezone.utc).isoformat()})
    except ValueError:
        return _json({"success": False, "error": "invalid JSON"}, 400)
    except Exception as exc:
        logger.exception("admin_ui_config failed")
        return _json({"success": False, "error": str(exc)}, 500)


@app.route(route="v1/model/status", methods=["GET"])
def model_status(req: func.HttpRequest) -> func.HttpResponse:
    try:
        repo = SupabaseRepository()
        account = _authenticated_account(req, repo)
        if not account:
            return _json({"success": False, "error": "unauthorized"}, 401)
        if not _feature_allowed(repo, account, "route.model"):
            return _json({"success": False, "error": "plan_required"}, 403)
        latest = repo.latest_model_version()
        return _json({"success": True, "model": latest})
    except Exception as exc:
        logger.exception("model_status failed")
        return _json({"success": False, "error": str(exc)}, 500)


@app.route(route="v1/backtest/latest", methods=["GET"])
def backtest_latest(req: func.HttpRequest) -> func.HttpResponse:
    try:
        repo = SupabaseRepository()
        account = _authenticated_account(req, repo)
        if not account:
            return _json({"success": False, "error": "unauthorized"}, 401)
        if not _feature_allowed(repo, account, "route.backtests"):
            return _json({"success": False, "error": "plan_required"}, 403)
        latest = repo.latest_backtest()
        return _json({"success": True, "backtest": latest})
    except Exception as exc:
        logger.exception("backtest_latest failed")
        return _json({"success": False, "error": str(exc)}, 500)
