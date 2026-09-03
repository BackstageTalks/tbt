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


def _close_provider(
    provider: RapidTennisClient,
) -> None:
    """
    Close the provider's underlying HTTP client.

    The current RapidTennisClient exposes the httpx client directly and
    does not define its own close() method.
    """

    client = getattr(
        provider,
        "client",
        None,
    )

    if client is not None:
        close = getattr(
            client,
            "close",
            None,
        )

        if callable(close):
            close()


def bootstrap_history(
    start_year: int,
    end_year: int,
    cfg: Settings = settings,
) -> dict:
    """
    Download real historical ATP/WTA results and persist them incrementally.

    The current provider exposes historical data by full calendar year.
    Each tour/year is therefore downloaded once.

    Existing Supabase rows are preserved through canonical upserts.
    No odds, statistics, rankings or environment data are fabricated here.
    """

    if end_year < start_year:
        raise ValueError(
            "end_year must be >= start_year"
        )

    provider = RapidTennisClient(
        cfg
    )

    repo = SupabaseRepository(
        cfg
    )

    report: dict = {
        "years": {},
        "matches_written": 0,
    }

    yesterday = (
        datetime.now(
            timezone.utc
        ).date()
        - timedelta(
            days=1
        )
    )

    try:
        for year in range(
            start_year,
            end_year + 1,
        ):
            if year > yesterday.year:
                logger.info(
                    "Skipping future year %s",
                    year,
                )

                continue

            year_report = {
                "atp": 0,
                "wta": 0,
                "canonical": 0,
                "written": 0,
            }

            year_matches = []

            for tour in (
                "atp",
                "wta",
            ):
                logger.info(
                    "Downloading %s history for %s",
                    tour.upper(),
                    year,
                )

                matches = (
                    provider.historical_year(
                        tour,
                        year,
                    )
                )

                completed = [
                    match
                    for match
                    in matches
                    if (
                        match.is_completed
                        and match.winner_id
                        and (
                            year
                            < yesterday.year
                            or (
                                match.scheduled_at
                                .astimezone(
                                    timezone.utc
                                )
                                .date()
                                <= yesterday
                            )
                        )
                    )
                ]

                year_report[
                    tour
                ] = len(
                    completed
                )

                year_matches.extend(
                    completed
                )

                logger.info(
                    "%s %s returned %s "
                    "completed canonical matches",
                    tour.upper(),
                    year,
                    len(
                        completed
                    ),
                )

            deduped = list(
                {
                    match.match_id: match
                    for match
                    in year_matches
                }.values()
            )

            year_report[
                "canonical"
            ] = len(
                deduped
            )

            written = (
                repo.upsert_matches(
                    deduped
                )
            )

            year_report[
                "written"
            ] = written

            report[
                "matches_written"
            ] += written

            report[
                "years"
            ][
                str(year)
            ] = year_report

            logger.info(
                "%s history complete: "
                "ATP=%s WTA=%s canonical=%s written=%s",
                year,
                year_report[
                    "atp"
                ],
                year_report[
                    "wta"
                ],
                year_report[
                    "canonical"
                ],
                written,
            )

    finally:
        _close_provider(
            provider
        )

    completed_in_db = len(
        repo.get_completed_matches()
    )

    report[
        "completed_matches_in_db"
    ] = completed_in_db

    report[
        "minimum_for_training"
    ] = cfg.min_train_matches

    if completed_in_db == 0:
        raise ProviderError(
            "Bootstrap finished but Supabase "
            "contains 0 completed matches. "
            "Refusing to train on an empty dataset."
        )

    if (
        completed_in_db
        < cfg.min_train_matches
    ):
        logger.warning(
            "Bootstrap stored %s completed "
            "matches; production training "
            "currently requires %s. "
            "Import more history before retraining.",
            completed_in_db,
            cfg.min_train_matches,
        )

    return report


def _fixture_pair_day_key(
    match,
) -> tuple[
    str,
    str,
    str,
    str,
]:
    p1, p2 = sorted(
        (
            str(
                match.player1_id
            ),
            str(
                match.player2_id
            ),
        )
    )

    return (
        str(
            match.tour
        ).lower(),
        (
            match.scheduled_at
            .astimezone(
                timezone.utc
            )
            .date()
            .isoformat()
        ),
        p1,
        p2,
    )


def _fixture_priority(
    match,
) -> tuple[
    int,
    int,
    float,
]:
    """
    Choose the strongest representation of one upcoming fixture.

    Prefer a provider event ID, then a richer raw payload, then the latest
    provider timestamp as a deterministic final tiebreak.
    """

    raw = (
        match.provider_payload
        if isinstance(
            match.provider_payload,
            dict,
        )
        else {}
    )

    has_provider_id = (
        1
        if (
            raw.get(
                "_tbt_provider_event_id"
            )
            or raw.get(
                "provider_event_id"
            )
            or raw.get(
                "eventId"
            )
            or raw.get(
                "id"
            )
        )
        else 0
    )

    return (
        has_provider_id,
        len(
            raw
        ),
        match.scheduled_at.timestamp(),
    )


def _dedupe_upcoming(
    matches: list,
) -> tuple[
    list,
    int,
]:
    """
    Collapse multiple provider representations of the same singles fixture.
    """

    chosen: dict[
        tuple[
            str,
            str,
            str,
            str,
        ],
        object,
    ] = {}

    duplicates = 0

    for match in sorted(
        matches,
        key=lambda item: (
            item.scheduled_at
        ),
    ):
        key = (
            _fixture_pair_day_key(
                match
            )
        )

        existing = (
            chosen.get(
                key
            )
        )

        if existing is None:
            chosen[
                key
            ] = match

            continue

        duplicates += 1

        if (
            _fixture_priority(
                match
            )
            > _fixture_priority(
                existing
            )
        ):
            chosen[
                key
            ] = match

    return (
        sorted(
            chosen.values(),
            key=lambda item: (
                item.scheduled_at
            ),
        ),
        duplicates,
    )


def _require_champion_artifact(
    repo: SupabaseRepository,
    model,
) -> dict:
    """
    Refuse production prediction generation unless the loaded artifact is
    exactly the current database champion.
    """

    champion = (
        repo.champion_model_version()
    )

    if not champion:
        raise RuntimeError(
            "No champion model is registered "
            "in Supabase. Refusing to generate "
            "production predictions."
        )

    champion_version = str(
        champion.get(
            "model_version"
        )
        or ""
    )

    artifact_version = str(
        getattr(
            model,
            "version",
            "",
        )
        or ""
    )

    if not artifact_version:
        raise RuntimeError(
            "Loaded model artifact has "
            "no model version."
        )

    if (
        artifact_version
        != champion_version
    ):
        raise RuntimeError(
            "Production model mismatch: "
            f"artifact={artifact_version}, "
            f"champion={champion_version}. "
            "Refusing to generate predictions "
            "with a non-champion artifact."
        )

    return champion


def refresh_predictions(
    cfg: Settings = settings,
) -> dict:
    """
    Refresh genuinely future ATP/WTA singles fixtures using the champion model.
    """

    provider = RapidTennisClient(
        cfg
    )

    repo = SupabaseRepository(
        cfg
    )

    model = load_model(
        cfg.model_artifact
    )

    champion = (
        _require_champion_artifact(
            repo,
            model,
        )
    )

    now = datetime.now(
        timezone.utc
    )

    today = now.date()

    horizon = (
        today
        + timedelta(
            days=max(
                cfg.prediction_horizon_days,
                1,
            )
        )
    )

    try:
        upcoming = []

        for tour in (
            "atp",
            "wta",
        ):
            upcoming.extend(
                provider.upcoming(
                    tour,
                    today,
                    horizon,
                )
            )

    finally:
        _close_provider(
            provider
        )

    upcoming = [
        match
        for match
        in upcoming
        if (
            match.scheduled_at
            > now
        )
    ]

    by_match = {
        match.match_id: match
        for match
        in upcoming
    }

    (
        upcoming,
        duplicate_fixtures_removed,
    ) = _dedupe_upcoming(
        list(
            by_match.values()
        )
    )

    repo.upsert_matches(
        upcoming
    )

    history = (
        repo.get_completed_matches(
            before=now
        )
    )

    predictions = (
        predict_matches(
            model,
            history,
            upcoming,
        )
    )

    cleanup_end = (
        datetime.combine(
            horizon
            + timedelta(
                days=1
            ),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
    )

    stale_predictions_removed = (
        repo.delete_future_unsettled_predictions(
            model.version,
            now,
            cleanup_end,
        )
    )

    written = (
        repo.upsert_predictions(
            predictions
        )
    )

    logger.info(
        "Refreshed %s predictions from %s "
        "validated fixtures using champion %s",
        written,
        len(
            upcoming
        ),
        model.version,
    )

    return {
        "predictions": written,
        "fixtures": len(
            upcoming
        ),
        "model_version": (
            model.version
        ),
        "lifecycle_status": (
            champion.get(
                "lifecycle_status"
            )
        ),
        "fixture_source": (
            "RapidTennisClient.upcoming"
        ),
        "duplicate_fixtures_removed": (
            duplicate_fixtures_removed
        ),
        "stale_future_predictions_removed": (
            stale_predictions_removed
        ),
    }


def sync_current_year_results(
    cfg: Settings = settings,
) -> dict:
    """
    Reconcile the previous seven completed UTC days.

    The provider exposes history by year, so the current year is fetched once
    per tour and then filtered locally to the required date window.
    """

    provider = RapidTennisClient(
        cfg
    )

    repo = SupabaseRepository(
        cfg
    )

    today = (
        datetime.now(
            timezone.utc
        ).date()
    )

    start = (
        today
        - timedelta(
            days=7
        )
    )

    end = (
        today
        - timedelta(
            days=1
        )
    )

    years = range(
        start.year,
        end.year + 1,
    )

    try:
        completed = []

        for year in years:
            for tour in (
                "atp",
                "wta",
            ):
                matches = (
                    provider.historical_year(
                        tour,
                        year,
                    )
                )

                completed.extend(
                    match
                    for match
                    in matches
                    if (
                        match.is_completed
                        and match.winner_id
                        and start
                        <= (
                            match.scheduled_at
                            .astimezone(
                                timezone.utc
                            )
                            .date()
                        )
                        <= end
                    )
                )

    finally:
        _close_provider(
            provider
        )

    completed = list(
        {
            match.match_id: match
            for match
            in completed
        }.values()
    )

    upserted = (
        repo.upsert_matches(
            completed
        )
    )

    settled = (
        repo.settle_predictions(
            completed
        )
    )

    return {
        "window_start": (
            start.isoformat()
        ),
        "window_end": (
            end.isoformat()
        ),
        "completed_matches_found": (
            len(
                completed
            )
        ),
        "completed_matches_upserted": (
            upserted
        ),
        "predictions_settled": (
            settled
        ),
    }
