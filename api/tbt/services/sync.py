from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ..config import Settings, settings
from ..models.artifact import load_model
from ..providers.rapidapi import RapidTennisClient
from ..repositories.supabase import SupabaseRepository
from .notifications import telegram_message
from .predictor import predict_matches

logger = logging.getLogger(__name__)


def bootstrap_history(
    start_year: int,
    end_year: int,
    cfg: Settings = settings,
) -> dict:
    provider = RapidTennisClient(cfg)
    repo = SupabaseRepository(cfg)
    report = {"years": {}, "matches": 0}
    for year in range(start_year, end_year + 1):
        for tour in ("atp", "wta"):
            matches = provider.historical_year(tour, year)
            written = repo.upsert_matches(matches)
            report["years"][f"{tour}-{year}"] = written
            report["matches"] += written
    return report


def refresh_predictions(cfg: Settings = settings) -> dict:
    provider = RapidTennisClient(cfg)
    repo = SupabaseRepository(cfg)
    model = load_model(cfg.model_artifact)
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=max(cfg.prediction_horizon_days, 1))

    upcoming = []
    for tour in ("atp", "wta"):
        upcoming.extend(provider.upcoming(tour, today, horizon))
    # Dedupe in case provider pagination/range returns duplicates.
    upcoming = list({m.match_id: m for m in upcoming}.values())
    repo.upsert_matches(upcoming)
    history = repo.get_completed_matches(before=datetime.now(timezone.utc) + timedelta(days=1))
    predictions = predict_matches(model, history, upcoming)
    written = repo.upsert_predictions(predictions)
    logger.info("Refreshed %s predictions using %s", written, model.version)
    return {"predictions": written, "fixtures": len(upcoming), "model_version": model.version}


def sync_current_year_results(cfg: Settings = settings) -> dict:
    provider = RapidTennisClient(cfg)
    repo = SupabaseRepository(cfg)
    year = datetime.now(timezone.utc).year
    completed = []
    for tour in ("atp", "wta"):
        completed.extend(provider.historical_year(tour, year))
    completed = list({m.match_id: m for m in completed if m.is_completed}.values())
    upserted = repo.upsert_matches(completed)
    settled = repo.settle_predictions(completed)
    return {"completed_matches_upserted": upserted, "predictions_settled": settled}
