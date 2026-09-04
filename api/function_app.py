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
                "ranking": "BlinQ Prime Score",
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
