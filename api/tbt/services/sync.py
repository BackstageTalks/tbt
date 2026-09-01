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

    Data are written month-by-month. No odds/statistics/weather calls are made in
    this bulk step; those are separate enrichment layers so the tennis quota and
    provenance remain auditable.
    """
    if end_year < start_year:
        raise ValueError("end_year must be >= start_year")

    provider = RapidTennisClient(cfg)
    repo = SupabaseRepository(cfg)
    report: dict = {"years": {}, "matches_written": 0, "rapidapi_requests": 0}
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)

    try:
        for year in range(start_year, end_year + 1):
            year_report = {"atp": 0, "wta": 0, "written": 0}

            for month in range(1, 13):
                month_start = date(year, month, 1)
                month_end = date(year, month, calendar.monthrange(year, month)[1])
                if month_start > yesterday:
                    break
                month_end = min(month_end, yesterday)

                month_matches = []
                for tour in ("atp", "wta"):
                    logger.info(
                        "Downloading %s history for %04d-%02d",
                        tour.upper(), year, month,
                    )
                    matches = provider.historical_period(tour, month_start, month_end)
                    completed = [m for m in matches if m.is_completed and m.winner_id]
                    year_report[tour] += len(completed)
                    month_matches.extend(completed)

                deduped = list({m.match_id: m for m in month_matches}.values())
                written = repo.upsert_matches(deduped)
                year_report["written"] += written
                report["matches_written"] += written

                logger.info(
                    "%04d-%02d stored %s real completed matches; "
                    "RapidAPI requests=%s remaining=%s/%s",
                    year, month, written, provider.request_count,
                    provider.rate_limit_remaining, provider.rate_limit_limit,
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
    if completed_in_db < cfg.min_train_matches:
        logger.warning(
            "Bootstrap stored %s completed matches; production training currently "
            "requires %s. Import more history before retraining.",
            completed_in_db, cfg.min_train_matches,
        )
    return report


def _fixture_pair_day_key(match) -> tuple[str, str, str, str]:
    p1, p2 = sorted((str(match.player1_id), str(match.player2_id)))
    return (
        str(match.tour).lower(),
        match.scheduled_at.astimezone(timezone.utc).date().isoformat(),
        p1,
        p2,
    )


def _fixture_priority(match) -> tuple[int, int, float]:
    """Choose the strongest provider representation of one real fixture.

    Grand Slam category wins over a duplicate ATP/WTA category representation.
    Then prefer the row carrying a stable provider event id and, as a final
    deterministic tiebreak, the later provider start timestamp (reschedules tend
    to supersede earlier provisional times).
    """
    raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    try:
        category_id = int(raw.get("_tbt_source_category_id"))
    except (TypeError, ValueError):
        category_id = 0

    is_grand_slam = 1 if category_id == RapidTennisClient.CATEGORY_GRAND_SLAM else 0
    has_provider_id = 1 if raw.get("_tbt_provider_event_id") or raw.get("id") else 0
    return (is_grand_slam, has_provider_id, match.scheduled_at.timestamp())


def _dedupe_upcoming(matches: list) -> tuple[list, int]:
    """Collapse duplicate provider representations of the same singles fixture.

    Two singles players cannot play two separate official matches against each
    other on the same tour/date in the normal TBT coverage model. Grouping by
    unordered player pair + UTC date removes category aliases such as
    ``US Open, Women`` vs ``US Open, New York, USA`` without relying on names.
    """
    chosen: dict[tuple[str, str, str, str], object] = {}
    duplicates = 0
    for match in sorted(matches, key=lambda m: m.scheduled_at):
        key = _fixture_pair_day_key(match)
        existing = chosen.get(key)
        if existing is None:
            chosen[key] = match
            continue
        duplicates += 1
        if _fixture_priority(match) > _fixture_priority(existing):
            chosen[key] = match
    return sorted(chosen.values(), key=lambda m: m.scheduled_at), duplicates


def refresh_predictions(cfg: Settings = settings) -> dict:
    """Refresh only genuinely future, non-cancelled ATP/WTA singles fixtures."""
    provider = RapidTennisClient(cfg)
    repo = SupabaseRepository(cfg)
    model = load_model(cfg.model_artifact)

    now = datetime.now(timezone.utc)
    today = now.date()
    horizon = today + timedelta(days=max(cfg.prediction_horizon_days, 1))

    try:
        upcoming = []
        for tour in ("atp", "wta"):
            upcoming.extend(provider.upcoming(tour, today, horizon))
        rapidapi_requests = provider.request_count
        rapidapi_remaining = provider.rate_limit_remaining
    finally:
        provider.close()

    # A fixture must be in the future at prediction creation time. This prevents
    # a same-day refresh from creating fresh "pre-match" predictions after start.
    upcoming = [m for m in upcoming if m.scheduled_at > now]

    # First collapse exact canonical IDs, then collapse duplicate provider
    # representations of the same player pair/date (e.g. Grand Slam aliases).
    by_match = {m.match_id: m for m in upcoming}
    upcoming, duplicate_fixtures_removed = _dedupe_upcoming(list(by_match.values()))

    repo.upsert_matches(upcoming)

    history = repo.get_completed_matches(before=now)
    predictions = predict_matches(model, history, upcoming)

    # Replace only FUTURE, UNSETTLED rows for this model. Historical/started
    # predictions stay in the DB for audit and settlement.
    cleanup_end = datetime.combine(
        horizon + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )
    stale_predictions_removed = repo.delete_future_unsettled_predictions(
        model.version, now, cleanup_end
    )
    written = repo.upsert_predictions(predictions)

    logger.info(
        "Refreshed %s predictions from %s validated fixtures using %s",
        written, len(upcoming), model.version,
    )
    return {
        "predictions": written,
        "fixtures": len(upcoming),
        "model_version": model.version,
        "rapidapi_requests": rapidapi_requests,
        "rapidapi_remaining": rapidapi_remaining,
        "fixture_source": "calendar/categories -> category/events",
        "duplicate_fixtures_removed": duplicate_fixtures_removed,
        "stale_future_predictions_removed": stale_predictions_removed,
    }


def sync_current_year_results(cfg: Settings = settings) -> dict:
    provider = RapidTennisClient(cfg)
    repo = SupabaseRepository(cfg)
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=7)
    end = today - timedelta(days=1)

    try:
        completed = []
        for tour in ("atp", "wta"):
            completed.extend(provider.historical_period(tour, start, end))
        rapidapi_requests = provider.request_count
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
        "rapidapi_requests": rapidapi_requests,
    }
