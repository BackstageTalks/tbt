from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ..config import Settings, settings
from ..errors import ProviderError
from ..models.artifact import load_model
from ..providers.rapidapi import RapidTennisClient
from ..repositories.supabase import SupabaseRepository
from .predictor import predict_matches

logger = logging.getLogger(__name__)


def bootstrap_history(
    start_year: int,
    end_year: int,
    cfg: Settings = settings,
) -> dict:
    """Download real historical matches and persist them to Supabase.

    A bootstrap is considered successful only when completed matches were really
    stored.  This prevents a green GitHub Action from hiding an empty provider
    result and later failing during training with "Only 0 completed matches".
    """

    provider = RapidTennisClient(cfg)
    repo = SupabaseRepository(cfg)
    report: dict = {"years": {}, "matches_written": 0}

    try:
        for year in range(start_year, end_year + 1):
            for tour in ("atp", "wta"):
                logger.info("Downloading %s history for %s", tour.upper(), year)
                matches = provider.historical_year(tour, year)
                completed = [m for m in matches if m.is_completed and m.winner_id]

                logger.info(
                    "%s %s: provider returned %s completed matches",
                    tour.upper(),
                    year,
                    len(completed),
                )

                written = repo.upsert_matches(completed)
                report["years"][f"{tour}-{year}"] = {
                    "provider_completed": len(completed),
                    "written": written,
                }
                report["matches_written"] += written
    finally:
        provider.close()

    # Verify the real database state rather than trusting request success codes.
    completed_in_db = len(repo.get_completed_matches())
    report["completed_matches_in_db"] = completed_in_db
    report["minimum_for_training"] = cfg.min_train_matches

    if completed_in_db == 0:
        raise ProviderError(
            "Historical bootstrap completed HTTP requests but Supabase still contains "
            "0 completed matches. The provider mapping/filtering returned no usable "
            "real results; refusing to continue with an empty dataset."
        )

    if completed_in_db < cfg.min_train_matches:
        raise ProviderError(
            f"Historical bootstrap stored only {completed_in_db} completed matches, "
            f"but training requires at least {cfg.min_train_matches}. Extend the "
            "bootstrap period or fix provider coverage before training."
        )

    logger.info(
        "Bootstrap verified: %s completed matches available in Supabase",
        completed_in_db,
    )
    return report


def refresh_predictions(cfg: Settings = settings) -> dict:
    provider = RapidTennisClient(cfg)
    repo = SupabaseRepository(cfg)
    model = load_model(cfg.model_artifact)
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=max(cfg.prediction_horizon_days, 1))

    try:
        upcoming = []
        for tour in ("atp", "wta"):
            upcoming.extend(provider.upcoming(tour, today, horizon))
    finally:
        provider.close()

    # Dedupe in case provider date windows return overlapping events.
    upcoming = list({m.match_id: m for m in upcoming}.values())
    repo.upsert_matches(upcoming)

    history = repo.get_completed_matches(
        before=datetime.now(timezone.utc) + timedelta(days=1)
    )
    predictions = predict_matches(model, history, upcoming)
    written = repo.upsert_predictions(predictions)

    logger.info("Refreshed %s predictions using %s", written, model.version)
    return {
        "predictions": written,
        "fixtures": len(upcoming),
        "model_version": model.version,
    }


def sync_current_year_results(cfg: Settings = settings) -> dict:
    provider = RapidTennisClient(cfg)
    repo = SupabaseRepository(cfg)
    year = datetime.now(timezone.utc).year

    try:
        completed = []
        for tour in ("atp", "wta"):
            completed.extend(provider.historical_year(tour, year))
    finally:
        provider.close()

    completed = list(
        {
            m.match_id: m
            for m in completed
            if m.is_completed and m.winner_id
        }.values()
    )

    upserted = repo.upsert_matches(completed)
    settled = repo.settle_predictions(completed)
    return {
        "completed_matches_upserted": upserted,
        "predictions_settled": settled,
    }
