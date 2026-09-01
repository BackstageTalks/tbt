from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timedelta, timezone

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
    """Download only real historical match results and persist them incrementally.

    Data are written month-by-month. A failed run therefore keeps already imported
    months in Supabase and can safely be rerun because ``match_id`` is upserted.
    No odds/statistics requests are made during this bulk history step.
    """

    if end_year < start_year:
        raise ValueError("end_year must be >= start_year")

    provider = RapidTennisClient(cfg)
    repo = SupabaseRepository(cfg)
    report: dict = {
        "years": {},
        "matches_written": 0,
        "rapidapi_requests": 0,
    }

    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)

    try:
        for year in range(start_year, end_year + 1):
            year_report = {"atp": 0, "wta": 0, "written": 0}

            for month in range(1, 13):
                month_start = date(year, month, 1)
                month_end = date(year, month, calendar.monthrange(year, month)[1])

                # Never consume quota on future dates in the current/future year.
                if month_start > yesterday:
                    break
                month_end = min(month_end, yesterday)

                month_matches = []
                for tour in ("atp", "wta"):
                    logger.info(
                        "Downloading %s history for %04d-%02d",
                        tour.upper(),
                        year,
                        month,
                    )
                    matches = provider.historical_period(tour, month_start, month_end)
                    completed = [m for m in matches if m.is_completed and m.winner_id]
                    year_report[tour] += len(completed)
                    month_matches.extend(completed)

                # Shared categories/day boundaries can produce duplicates. Store once.
                deduped = list({m.match_id: m for m in month_matches}.values())
                written = repo.upsert_matches(deduped)
                year_report["written"] += written
                report["matches_written"] += written

                logger.info(
                    "%04d-%02d stored %s real completed matches; "
                    "RapidAPI requests=%s remaining=%s/%s",
                    year,
                    month,
                    written,
                    provider.request_count,
                    provider.rate_limit_remaining,
                    provider.rate_limit_limit,
                )

            report["years"][str(year)] = year_report

    finally:
        report["rapidapi_requests"] = provider.request_count
        report["rapidapi_remaining"] = provider.rate_limit_remaining
        report["rapidapi_limit"] = provider.rate_limit_limit
        provider.close()

    completed_in_db = len(repo.get_completed_matches())
    report["completed_matches_in_db"] = completed_in_db
    report["minimum_for_training"] = cfg.min_train_matches

    if completed_in_db == 0:
        raise ProviderError(
            "Bootstrap finished but Supabase contains 0 completed matches. "
            "Refusing to train on an empty dataset."
        )

    # For a partial/current-year bootstrap we keep the real imported data even if
    # it is below the production threshold. Training will enforce its own minimum.
    if completed_in_db < cfg.min_train_matches:
        logger.warning(
            "Bootstrap stored %s completed matches; production training currently "
            "requires %s. Import more history before retraining.",
            completed_in_db,
            cfg.min_train_matches,
        )
    else:
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
    today = datetime.now(timezone.utc).date()

    # Daily reconciliation should only revisit a short rolling window, not download
    # the whole current year every day. Older results are already persisted.
    start = today - timedelta(days=7)
    end = today - timedelta(days=1)

    try:
        completed = []
        for tour in ("atp", "wta"):
            completed.extend(provider.historical_period(tour, start, end))
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
