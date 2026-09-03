from __future__ import annotations

import argparse
import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

from _bootstrap import ROOT  # noqa: F401

from tbt.repositories.supabase import SupabaseRepository
from tbt.services.environment import (
    OpenMeteoClient,
    environment_payload,
    location_candidates,
)


logger = logging.getLogger(
    "tbt.enrich_environment"
)


ENVIRONMENT_SCHEMA_VERSION = 2

CANONICAL_WEATHER_FIELDS = (
    "temperature_c",
    "relative_humidity_pct",
    "precipitation_mm",
    "wind_speed_kmh",
    "wind_gusts_kmh",
    "surface_pressure_hpa",
    "weather_code",
    "source_time_utc",
)

CORE_WEATHER_FIELDS = (
    "temperature_c",
    "relative_humidity_pct",
    "wind_speed_kmh",
)


def parse_utc(
    value: str,
) -> datetime:
    text = value.strip()

    if len(text) == 10:
        text += (
            "T00:00:00+00:00"
        )

    dt = datetime.fromisoformat(
        text.replace(
            "Z",
            "+00:00",
        )
    )

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt.astimezone(
        timezone.utc
    )


def _as_dict(
    value: Any,
) -> dict[str, Any]:
    return (
        value
        if isinstance(
            value,
            dict,
        )
        else {}
    )


def _safe_number(
    value: Any,
) -> float | None:
    try:
        if value is None:
            return None

        number = float(
            value
        )

        if not math.isfinite(
            number
        ):
            return None

        return number

    except (
        TypeError,
        ValueError,
    ):
        return None


def _weather_schema_is_current(
    weather: dict[str, Any],
) -> bool:
    """
    A current weather payload uses the canonical TBT field names.

    Old payloads used raw Open-Meteo names such as temperature_2m,
    relative_humidity_2m and wind_speed_10m. Those must be re-enriched.
    """

    return all(
        field in weather
        for field
        in CANONICAL_WEATHER_FIELDS
    )


def _weather_is_usable(
    weather: dict[str, Any],
) -> bool:
    """
    Require the three core weather observations actually consumed by the
    model. Merely having a weather dictionary is not sufficient.
    """

    return all(
        _safe_number(
            weather.get(
                field
            )
        )
        is not None
        for field
        in CORE_WEATHER_FIELDS
    )


def _environment_state(
    existing: Any,
) -> str:
    """
    Classify an existing enrichment.

    Returns:
      missing
      unresolved
      stale_schema
      incomplete_weather
      current
    """

    if not isinstance(
        existing,
        dict,
    ):
        return "missing"

    if (
        existing.get(
            "venue_resolved"
        )
        is not True
    ):
        return "unresolved"

    weather = _as_dict(
        existing.get(
            "weather"
        )
    )

    schema_version = (
        existing.get(
            "schema_version"
        )
    )

    if (
        schema_version
        != ENVIRONMENT_SCHEMA_VERSION
        or not _weather_schema_is_current(
            weather
        )
    ):
        return "stale_schema"

    if not _weather_is_usable(
        weather
    ):
        return "incomplete_weather"

    return "current"


def _provider_diagnostics(
    payload: dict[str, Any],
) -> dict[str, Any]:
    tournament = _as_dict(
        payload.get(
            "tournament"
        )
    )

    unique = _as_dict(
        tournament.get(
            "uniqueTournament"
        )
    )

    category = _as_dict(
        tournament.get(
            "category"
        )
    )

    venue = _as_dict(
        payload.get(
            "venue"
        )
    )

    country = (
        _as_dict(
            tournament.get(
                "country"
            )
        )
        or _as_dict(
            unique.get(
                "country"
            )
        )
    )

    return {
        "provider_event_id": (
            payload.get(
                "id"
            )
        ),
        "provider_tournament": (
            tournament.get(
                "name"
            )
        ),
        "provider_tournament_id": (
            tournament.get(
                "id"
            )
        ),
        "provider_unique_tournament": (
            unique.get(
                "name"
            )
        ),
        "provider_unique_tournament_id": (
            unique.get(
                "id"
            )
        ),
        "provider_category": (
            category.get(
                "name"
            )
        ),
        "provider_category_id": (
            category.get(
                "id"
            )
        ),
        "provider_venue": (
            venue.get(
                "name"
            )
        ),
        "provider_city": (
            venue.get(
                "city"
            )
            or tournament.get(
                "city"
            )
            or unique.get(
                "city"
            )
            or payload.get(
                "city"
            )
            or payload.get(
                "venueCity"
            )
        ),
        "provider_country": (
            _as_dict(
                venue.get(
                    "country"
                )
            ).get(
                "name"
            )
            or venue.get(
                "countryName"
            )
            or country.get(
                "name"
            )
            or payload.get(
                "countryName"
            )
            or _as_dict(
                payload.get(
                    "country"
                )
            ).get(
                "name"
            )
        ),
        "tbt_source_category_id": (
            payload.get(
                "_tbt_source_category_id"
            )
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill canonical Open-Meteo weather/elevation into "
            "match provider_payload and automatically migrate stale "
            "environment payload schemas."
        )
    )

    parser.add_argument(
        "--start",
        required=True,
    )

    parser.add_argument(
        "--end",
        required=True,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--force",
        action="store_true",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    parser.add_argument(
        "--sleep-ms",
        type=int,
        default=50,
    )

    parser.add_argument(
        "--diagnostics-limit",
        type=int,
        default=100,
        help=(
            "Maximum diagnostic rows included "
            "in the final JSON report."
        ),
    )

    args = parser.parse_args()

    start = parse_utc(
        args.start
    )

    end = parse_utc(
        args.end
    )

    if end <= start:
        raise SystemExit(
            "--end must be later than --start"
        )

    repo = SupabaseRepository()

    weather_client = (
        OpenMeteoClient()
    )

    report: dict[
        str,
        Any,
    ] = {
        "start": (
            start.isoformat()
        ),
        "end": (
            end.isoformat()
        ),
        "environment_schema_version": (
            ENVIRONMENT_SCHEMA_VERSION
        ),
        "inspected": 0,
        "already_current": 0,
        "missing": 0,
        "unresolved_existing": 0,
        "stale_schema": 0,
        "incomplete_weather": 0,
        "forced": 0,
        "resolved": 0,
        "weather_usable": 0,
        "weather_incomplete_after_refresh": 0,
        "unresolved": 0,
        "updated": 0,
        "errors": 0,
        "dry_run": bool(
            args.dry_run
        ),
        "unresolved_details": [],
        "resolved_details": [],
        "incomplete_weather_details": [],
        "error_details": [],
    }

    try:
        matches = (
            repo.get_matches_between(
                start,
                end,
                completed_only=True,
            )
        )

        if args.limit > 0:
            matches = matches[
                : args.limit
            ]

        for (
            index,
            match,
        ) in enumerate(
            matches,
            start=1,
        ):
            report[
                "inspected"
            ] += 1

            payload = dict(
                match.provider_payload
                or {}
            )

            existing = (
                payload.get(
                    "_tbt_environment"
                )
            )

            state = (
                _environment_state(
                    existing
                )
            )

            if args.force:
                report[
                    "forced"
                ] += 1

            else:
                if state == "current":
                    report[
                        "already_current"
                    ] += 1
                    continue

                report[
                    state
                ] += 1

            candidates = (
                location_candidates(
                    payload,
                    match.tournament,
                )
            )

            provider_diag = (
                _provider_diagnostics(
                    payload
                )
            )

            try:
                env = (
                    environment_payload(
                        weather_client,
                        payload,
                        match.tournament,
                        match.scheduled_at,
                    )
                )

                env[
                    "schema_version"
                ] = (
                    ENVIRONMENT_SCHEMA_VERSION
                )

                payload[
                    "_tbt_environment"
                ] = env

                detail = {
                    "match_id": (
                        match.match_id
                    ),
                    "scheduled_at": (
                        match.scheduled_at
                        .astimezone(
                            timezone.utc
                        )
                        .isoformat()
                    ),
                    "tour": (
                        match.tour
                    ),
                    "tournament": (
                        match.tournament
                    ),
                    "tournament_id": (
                        match.tournament_id
                    ),
                    "round_name": (
                        match.round_name
                    ),
                    "player1": (
                        match.player1_name
                    ),
                    "player2": (
                        match.player2_name
                    ),
                    "previous_environment_state": (
                        state
                    ),
                    "location_candidates": (
                        candidates
                    ),
                    **provider_diag,
                }

                if env.get(
                    "venue_resolved"
                ):
                    report[
                        "resolved"
                    ] += 1

                    detail[
                        "resolved_query"
                    ] = (
                        env.get(
                            "location_query"
                        )
                    )

                    detail[
                        "resolved_venue"
                    ] = (
                        env.get(
                            "venue"
                        )
                    )

                    current_weather = (
                        _as_dict(
                            env.get(
                                "weather"
                            )
                        )
                    )

                    if _weather_is_usable(
                        current_weather
                    ):
                        report[
                            "weather_usable"
                        ] += 1

                    else:
                        report[
                            "weather_incomplete_after_refresh"
                        ] += 1

                        detail[
                            "weather"
                        ] = (
                            current_weather
                        )

                        if (
                            len(
                                report[
                                    "incomplete_weather_details"
                                ]
                            )
                            < args.diagnostics_limit
                        ):
                            report[
                                "incomplete_weather_details"
                            ].append(
                                detail
                            )

                    if (
                        len(
                            report[
                                "resolved_details"
                            ]
                        )
                        < args.diagnostics_limit
                    ):
                        report[
                            "resolved_details"
                        ].append(
                            detail
                        )

                else:
                    report[
                        "unresolved"
                    ] += 1

                    if (
                        len(
                            report[
                                "unresolved_details"
                            ]
                        )
                        < args.diagnostics_limit
                    ):
                        report[
                            "unresolved_details"
                        ].append(
                            detail
                        )

                if not args.dry_run:
                    report[
                        "updated"
                    ] += (
                        repo.update_match_provider_payload(
                            match.match_id,
                            payload,
                        )
                    )

            except Exception as exc:
                report[
                    "errors"
                ] += 1

                logger.warning(
                    "Environment enrichment failed "
                    "match=%s tournament=%r: %s",
                    match.match_id,
                    match.tournament,
                    exc,
                )

                if (
                    len(
                        report[
                            "error_details"
                        ]
                    )
                    < args.diagnostics_limit
                ):
                    report[
                        "error_details"
                    ].append(
                        {
                            "match_id": (
                                match.match_id
                            ),
                            "scheduled_at": (
                                match.scheduled_at
                                .astimezone(
                                    timezone.utc
                                )
                                .isoformat()
                            ),
                            "tour": (
                                match.tour
                            ),
                            "tournament": (
                                match.tournament
                            ),
                            "tournament_id": (
                                match.tournament_id
                            ),
                            "previous_environment_state": (
                                state
                            ),
                            "location_candidates": (
                                candidates
                            ),
                            "error": (
                                f"{type(exc).__name__}: "
                                f"{exc}"
                            ),
                            **provider_diag,
                        }
                    )

            if index % 250 == 0:
                logger.info(
                    "Progress %s/%s "
                    "current=%s stale=%s "
                    "incomplete=%s resolved=%s "
                    "weather_usable=%s "
                    "unresolved=%s errors=%s",
                    index,
                    len(
                        matches
                    ),
                    report[
                        "already_current"
                    ],
                    report[
                        "stale_schema"
                    ],
                    report[
                        "incomplete_weather"
                    ],
                    report[
                        "resolved"
                    ],
                    report[
                        "weather_usable"
                    ],
                    report[
                        "unresolved"
                    ],
                    report[
                        "errors"
                    ],
                )

            if args.sleep_ms > 0:
                time.sleep(
                    args.sleep_ms
                    / 1000.0
                )

    finally:
        weather_client.close()

    report[
        "refresh_candidates"
    ] = (
        report[
            "missing"
        ]
        + report[
            "unresolved_existing"
        ]
        + report[
            "stale_schema"
        ]
        + report[
            "incomplete_weather"
        ]
        + report[
            "forced"
        ]
    )

    print(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "%(levelname)s "
            "%(name)s: "
            "%(message)s"
        ),
    )

    main()
