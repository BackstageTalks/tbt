from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import azure.functions as func

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


@app.route(route="v1/predictions/status", methods=["GET"])
def predictions_status(req: func.HttpRequest) -> func.HttpResponse:
    try:
        status = _prediction_status(SupabaseRepository())
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


@app.route(route="v1/predictions/upcoming", methods=["GET"])
def predictions_upcoming(req: func.HttpRequest) -> func.HttpResponse:
    try:
        days = max(
            1,
            min(int(req.params.get("days", settings.prediction_horizon_days)), 14),
        )
        tour = req.params.get("tour")
        if tour and tour.lower() not in {"atp", "wta"}:
            return _json({"error": "tour must be ATP or WTA"}, 400)

        now = datetime.now(timezone.utc) - timedelta(hours=6)
        end = now + timedelta(days=days)
        rows = SupabaseRepository().list_predictions(now, end, tour=tour)
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
        rows = SupabaseRepository().list_predictions(now, end, tour=tour)
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
        latest = SupabaseRepository().latest_model_version()
        return _json({"success": True, "model": latest})
    except Exception as exc:
        logger.exception("model_status failed")
        return _json({"success": False, "error": str(exc)}, 500)


@app.route(route="v1/backtest/latest", methods=["GET"])
def backtest_latest(req: func.HttpRequest) -> func.HttpResponse:
    try:
        latest = SupabaseRepository().latest_backtest()
        return _json({"success": True, "backtest": latest})
    except Exception as exc:
        logger.exception("backtest_latest failed")
        return _json({"success": False, "error": str(exc)}, 500)
