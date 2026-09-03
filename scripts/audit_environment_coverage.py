from __future__ import annotations

import json
import math
from typing import Any

from _bootstrap import ROOT  # noqa: F401

from tbt.repositories.supabase import SupabaseRepository


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

LEGACY_WEATHER_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_gusts_10m",
    "surface_pressure",
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

        number = float(value)

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


def _payload(
    row: dict[str, Any],
) -> dict[str, Any]:
    return _as_dict(
        row.get(
            "provider_payload"
        )
    )


def _environment_from_row(
    row: dict[str, Any],
) -> dict[str, Any]:
    payload = _payload(
        row
    )

    return _as_dict(
        payload.get(
            "_tbt_environment"
        )
    )


def _provider_event_id_from_payload(
    payload: dict[str, Any],
) -> str | None:
    for key in (
        "_tbt_provider_event_id",
        "provider_event_id",
        "event_id",
        "eventId",
    ):
        value = payload.get(
            key
        )

        if value not in (
            None,
            "",
        ):
            return str(
                value
            )

    event = payload.get(
        "event"
    )

    if isinstance(
        event,
        dict,
    ):
        value = event.get(
            "id"
        )

        if value not in (
            None,
            "",
        ):
            return str(
                value
            )

    value = payload.get(
        "id"
    )

    if value not in (
        None,
        "",
    ):
        return str(
            value
        )

    return None


def _provider_event_id_from_row(
    row: dict[str, Any],
) -> str | None:
    return (
        _provider_event_id_from_payload(
            _payload(
                row
            )
        )
    )


def _weather_schema_current(
    weather: dict[str, Any],
) -> bool:
    return all(
        field in weather
        for field
        in CANONICAL_WEATHER_FIELDS
    )


def _weather_has_legacy_fields(
    weather: dict[str, Any],
) -> bool:
    return any(
        field in weather
        for field
        in LEGACY_WEATHER_FIELDS
    )


def _weather_usable(
    weather: dict[str, Any],
) -> bool:
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
    env: dict[str, Any],
) -> str:
    if not env:
        return "missing"

    if (
        env.get(
            "venue_resolved"
        )
        is not True
    ):
        return "unresolved"

    weather = _as_dict(
        env.get(
            "weather"
        )
    )

    if not weather:
        return "no_weather"

    if _weather_has_legacy_fields(
        weather
    ):
        return "legacy_weather_schema"

    if (
        env.get(
            "schema_version"
        )
        != ENVIRONMENT_SCHEMA_VERSION
        or not _weather_schema_current(
            weather
        )
    ):
        return "stale_schema"

    if not _weather_usable(
        weather
    ):
        return "incomplete_weather"

    return "usable"


def _env_summary(
    env: dict[str, Any],
) -> dict[str, Any]:
    venue = _as_dict(
        env.get(
            "venue"
        )
    )

    weather = _as_dict(
        env.get(
            "weather"
        )
    )

    return {
        "schema_version": (
            env.get(
                "schema_version"
            )
        ),
        "state": (
            _environment_state(
                env
            )
        ),
        "venue_resolved": (
            env.get(
                "venue_resolved"
            )
        ),
        "location_query": (
            env.get(
                "location_query"
            )
        ),
        "source": (
            env.get(
                "source"
            )
        ),
        "venue": {
            "name": (
                venue.get(
                    "name"
                )
            ),
            "country": (
                venue.get(
                    "country"
                )
            ),
            "latitude": (
                venue.get(
                    "latitude"
                )
            ),
            "longitude": (
                venue.get(
                    "longitude"
                )
            ),
            "elevation_m": (
                venue.get(
                    "elevation_m"
                )
            ),
            "timezone": (
                venue.get(
                    "timezone"
                )
            ),
        },
        "weather_present": bool(
            weather
        ),
        "weather_schema_current": (
            _weather_schema_current(
                weather
            )
        ),
        "weather_usable": (
            _weather_usable(
                weather
            )
        ),
        "weather": {
            "temperature_c": (
                weather.get(
                    "temperature_c"
                )
            ),
            "relative_humidity_pct": (
                weather.get(
                    "relative_humidity_pct"
                )
            ),
            "precipitation_mm": (
                weather.get(
                    "precipitation_mm"
                )
            ),
            "wind_speed_kmh": (
                weather.get(
                    "wind_speed_kmh"
                )
            ),
            "wind_gusts_kmh": (
                weather.get(
                    "wind_gusts_kmh"
                )
            ),
            "surface_pressure_hpa": (
                weather.get(
                    "surface_pressure_hpa"
                )
            ),
            "weather_code": (
                weather.get(
                    "weather_code"
                )
            ),
            "source_time_utc": (
                weather.get(
                    "source_time_utc"
                )
            ),
        },
        "legacy_weather": {
            key: (
                weather.get(
                    key
                )
            )
            for key
            in LEGACY_WEATHER_FIELDS
            if key in weather
        },
    }


def _empty_counts() -> dict[str, int]:
    return {
        "with_environment": 0,
        "venue_resolved": 0,
        "with_weather_object": 0,
        "schema_v2": 0,
        "usable_weather": 0,
        "legacy_weather_schema": 0,
        "stale_schema": 0,
        "incomplete_weather": 0,
        "no_weather": 0,
        "unresolved": 0,
    }


def _update_counts(
    counts: dict[str, int],
    env: dict[str, Any],
) -> None:
    if not env:
        return

    counts[
        "with_environment"
    ] += 1

    if (
        env.get(
            "venue_resolved"
        )
        is True
    ):
        counts[
            "venue_resolved"
        ] += 1

    weather = _as_dict(
        env.get(
            "weather"
        )
    )

    if weather:
        counts[
            "with_weather_object"
        ] += 1

    if (
        env.get(
            "schema_version"
        )
        == ENVIRONMENT_SCHEMA_VERSION
        and _weather_schema_current(
            weather
        )
    ):
        counts[
            "schema_v2"
        ] += 1

    state = _environment_state(
        env
    )

    if state == "usable":
        counts[
            "usable_weather"
        ] += 1

    elif state == "legacy_weather_schema":
        counts[
            "legacy_weather_schema"
        ] += 1

    elif state == "stale_schema":
        counts[
            "stale_schema"
        ] += 1

    elif state == "incomplete_weather":
        counts[
            "incomplete_weather"
        ] += 1

    elif state == "no_weather":
        counts[
            "no_weather"
        ] += 1

    elif state == "unresolved":
        counts[
            "unresolved"
        ] += 1


def _coverage_report(
    counts: dict[str, int],
    total: int,
) -> dict[str, Any]:
    denominator = (
        float(total)
        if total
        else 1.0
    )

    return {
        **counts,
        "environment_coverage": (
            counts[
                "with_environment"
            ]
            / denominator
            if total
            else 0.0
        ),
        "resolved_coverage": (
            counts[
                "venue_resolved"
            ]
            / denominator
            if total
            else 0.0
        ),
        "weather_object_coverage": (
            counts[
                "with_weather_object"
            ]
            / denominator
            if total
            else 0.0
        ),
        "schema_v2_coverage": (
            counts[
                "schema_v2"
            ]
            / denominator
            if total
            else 0.0
        ),
        "usable_weather_coverage": (
            counts[
                "usable_weather"
            ]
            / denominator
            if total
            else 0.0
        ),
    }


def main() -> None:
    repo = (
        SupabaseRepository()
    )

    raw_rows = repo.select_all(
        "matches",
        filters={
            "winner_id": (
                "not.is.null"
            ),
        },
        order=(
            "scheduled_at.asc"
        ),
    )

    canonical_matches = (
        repo.get_completed_matches()
    )

    raw_counts = (
        _empty_counts()
    )

    canonical_counts = (
        _empty_counts()
    )

    raw_provider_ids_with_env: set[
        str
    ] = set()

    canonical_provider_ids_with_env: set[
        str
    ] = set()

    examples_raw: list[
        dict[str, Any]
    ] = []

    examples_canonical: list[
        dict[str, Any]
    ] = []

    stale_examples: list[
        dict[str, Any]
    ] = []

    incomplete_examples: list[
        dict[str, Any]
    ] = []

    missing_on_canonical_but_exists_raw: list[
        dict[str, Any]
    ] = []

    for row in raw_rows:
        env = (
            _environment_from_row(
                row
            )
        )

        _update_counts(
            raw_counts,
            env,
        )

        provider_event_id = (
            _provider_event_id_from_row(
                row
            )
        )

        if (
            env
            and provider_event_id
        ):
            raw_provider_ids_with_env.add(
                provider_event_id
            )

        if (
            env
            and len(
                examples_raw
            )
            < 10
        ):
            examples_raw.append(
                {
                    "match_id": (
                        row.get(
                            "match_id"
                        )
                    ),
                    "scheduled_at": (
                        row.get(
                            "scheduled_at"
                        )
                    ),
                    "tour": (
                        row.get(
                            "tour"
                        )
                    ),
                    "tournament": (
                        row.get(
                            "tournament"
                        )
                    ),
                    "provider_event_id": (
                        provider_event_id
                    ),
                    "environment": (
                        _env_summary(
                            env
                        )
                    ),
                }
            )

    for match in canonical_matches:
        payload = (
            match.provider_payload
            if isinstance(
                match.provider_payload,
                dict,
            )
            else {}
        )

        env = _as_dict(
            payload.get(
                "_tbt_environment"
            )
        )

        provider_event_id = (
            _provider_event_id_from_payload(
                payload
            )
        )

        _update_counts(
            canonical_counts,
            env,
        )

        if env:
            if provider_event_id:
                canonical_provider_ids_with_env.add(
                    provider_event_id
                )

            summary = (
                _env_summary(
                    env
                )
            )

            example = {
                "match_id": (
                    match.match_id
                ),
                "scheduled_at": (
                    match.scheduled_at
                    .isoformat()
                ),
                "tour": (
                    match.tour
                ),
                "tournament": (
                    match.tournament
                ),
                "provider_event_id": (
                    provider_event_id
                ),
                "environment": (
                    summary
                ),
            }

            if (
                len(
                    examples_canonical
                )
                < 10
            ):
                examples_canonical.append(
                    example
                )

            state = (
                summary[
                    "state"
                ]
            )

            if (
                state
                in {
                    "legacy_weather_schema",
                    "stale_schema",
                }
                and len(
                    stale_examples
                )
                < 20
            ):
                stale_examples.append(
                    example
                )

            if (
                state
                in {
                    "incomplete_weather",
                    "no_weather",
                }
                and len(
                    incomplete_examples
                )
                < 20
            ):
                incomplete_examples.append(
                    example
                )

        elif (
            provider_event_id
            and provider_event_id
            in raw_provider_ids_with_env
            and len(
                missing_on_canonical_but_exists_raw
            )
            < 20
        ):
            missing_on_canonical_but_exists_raw.append(
                {
                    "match_id": (
                        match.match_id
                    ),
                    "scheduled_at": (
                        match.scheduled_at
                        .isoformat()
                    ),
                    "tour": (
                        match.tour
                    ),
                    "tournament": (
                        match.tournament
                    ),
                    "provider_event_id": (
                        provider_event_id
                    ),
                }
            )

    raw_total = len(
        raw_rows
    )

    canonical_total = len(
        canonical_matches
    )

    report = {
        "environment_schema_version": (
            ENVIRONMENT_SCHEMA_VERSION
        ),
        "usable_weather_definition": (
            list(
                CORE_WEATHER_FIELDS
            )
        ),
        "raw_completed_rows": (
            raw_total
        ),
        "canonical_completed_matches": (
            canonical_total
        ),
        "raw": (
            _coverage_report(
                raw_counts,
                raw_total,
            )
        ),
        "canonical": (
            _coverage_report(
                canonical_counts,
                canonical_total,
            )
        ),
        "provider_event_ids": {
            "raw_with_environment": (
                len(
                    raw_provider_ids_with_env
                )
            ),
            "canonical_with_environment": (
                len(
                    canonical_provider_ids_with_env
                )
            ),
        },
        "migration": {
            "canonical_rows_needing_schema_refresh": (
                canonical_counts[
                    "legacy_weather_schema"
                ]
                + canonical_counts[
                    "stale_schema"
                ]
            ),
            "canonical_rows_with_incomplete_weather": (
                canonical_counts[
                    "incomplete_weather"
                ]
                + canonical_counts[
                    "no_weather"
                ]
            ),
        },
        "missing_on_canonical_but_exists_raw": (
            missing_on_canonical_but_exists_raw
        ),
        "stale_examples": (
            stale_examples
        ),
        "incomplete_weather_examples": (
            incomplete_examples
        ),
        "examples_raw": (
            examples_raw
        ),
        "examples_canonical": (
            examples_canonical
        ),
    }

    print(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
