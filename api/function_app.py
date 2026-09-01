from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import azure.functions as func

from tbt.config import settings
from tbt.errors import ConfigurationError, ModelNotReadyError
from tbt.log import configure_logging
from tbt.repositories.supabase import SupabaseRepository
from tbt.services.notifications import telegram_message
from tbt.services.contracts import public_prediction, blinq_flat_prediction
from tbt.services.sync import refresh_predictions, sync_current_year_results

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
    if not settings.admin_api_key:
        return False
    supplied = req.headers.get("x-admin-key", "")
    return supplied == settings.admin_api_key


@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    artifact = Path(settings.model_artifact)
    return _json(
        {
            "ok": True,
            "service": "TBT v200",
            "utc": datetime.now(timezone.utc).isoformat(),
            "model_artifact_present": artifact.exists(),
            "rapidapi_configured": bool(settings.rapidapi_key),
            "supabase_configured": bool(settings.supabase_url and settings.supabase_anon_key),
            "secure_server_writes_configured": bool(settings.supabase_service_role_key),
            "admin_endpoint_configured": bool(settings.admin_api_key),
        }
    )


@app.route(route="v1/predictions/upcoming", methods=["GET"])
def predictions_upcoming(req: func.HttpRequest) -> func.HttpResponse:
    try:
        days = max(1, min(int(req.params.get("days", settings.prediction_horizon_days)), 14))
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


@app.route(route="blinq/predictions", methods=["GET"])
def blinq_predictions(req: func.HttpRequest) -> func.HttpResponse:
    """Thin compatibility contract intended for an existing Blinq frontend."""
    try:
        days = max(1, min(int(req.params.get("days", settings.prediction_horizon_days)), 14))
        now = datetime.now(timezone.utc) - timedelta(hours=6)
        rows = SupabaseRepository().list_predictions(now, now + timedelta(days=days))
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


@app.route(route="v1/model/status", methods=["GET"])
def model_status(req: func.HttpRequest) -> func.HttpResponse:
    try:
        latest = SupabaseRepository().latest_model_version()
        return _json({"success": True, "model": latest})
    except Exception as exc:
        return _json({"success": False, "error": str(exc)}, 500)


@app.route(route="v1/backtest/latest", methods=["GET"])
def backtest_latest(req: func.HttpRequest) -> func.HttpResponse:
    try:
        latest = SupabaseRepository().latest_backtest()
        return _json({"success": True, "backtest": latest})
    except Exception as exc:
        return _json({"success": False, "error": str(exc)}, 500)


@app.route(route="v1/admin/refresh", methods=["POST"])
def admin_refresh(req: func.HttpRequest) -> func.HttpResponse:
    if not _admin_authorized(req):
        return _json({"error": "unauthorized"}, 401)
    try:
        result = refresh_predictions()
        return _json({"success": True, **result})
    except (ConfigurationError, ModelNotReadyError) as exc:
        return _json({"success": False, "error": str(exc)}, 503)
    except Exception as exc:
        logger.exception("admin refresh failed")
        telegram_message(f"TBT v200 admin refresh failed: {exc}")
        return _json({"success": False, "error": str(exc)}, 500)


@app.timer_trigger(schedule="0 */30 * * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def refresh_timer(timer: func.TimerRequest) -> None:
    try:
        result = refresh_predictions()
        logger.info("prediction refresh timer: %s", result)
    except ModelNotReadyError:
        logger.warning("Prediction timer skipped: model artifact is not deployed yet")
    except Exception as exc:
        logger.exception("prediction timer failed")
        telegram_message(f"TBT v200 prediction refresh failed: {exc}")


@app.timer_trigger(schedule="0 20 3 * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def settle_timer(timer: func.TimerRequest) -> None:
    try:
        result = sync_current_year_results()
        logger.info("result settlement timer: %s", result)
    except Exception as exc:
        logger.exception("result settlement failed")
        telegram_message(f"TBT v200 result settlement failed: {exc}")
