from __future__ import annotations

import json
import math
from collections import Counter
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
    "wind_speed_10m",
    "wind_gusts_10m",
    "surface_pressure",
)


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def safe_number(
    value: Any,
) -> float | None:
    try:
        if value is None:
            return None

        number = float(value)

        if not math.isfinite(number):
            return None

        return number

    except (TypeError, ValueError):
        return None


def weather_usable(
    weather: dict[str, Any],
) -> bool:
    return all(
        safe_number(
            weather.get(field)
        )
        is not None
        for field in CORE_WEATHER_FIELDS
    )


def canonical_schema(
    weather: dict[str, Any],
) -> bool:
    return all(
        field in weather
        for field in CANONICAL_WEATHER_FIELDS
    )


def legacy_schema(
    weather: dict[str, Any],
) -> bool:
    return any(
        field in weather
        for field in LEGACY_WEATHER_FIELDS
    )


def environment(
    row: dict[str, Any],
) -> dict[str, Any]:
    payload = as_dict(
        row.get("provider_payload")
    )

    return as_dict(
        payload.get("_tbt_environment")
    )


def state(
    env: dict[str, Any],
) -> str:
    if not env:
        return "missing"

    if env.get("venue_resolved") is not True:
        return "unresolved"

    weather = as_dict(
        env.get("weather")
    )

    if not weather:
        return "no_weather"

    if legacy_schema(weather):
        return "legacy_weather_schema"

    if not canonical_schema(weather):
        return "noncanonical_weather"

    if not weather_usable(weather):
        return "incomplete_weather"

    if (
        env.get("schema_version")
        != ENVIRONMENT_SCHEMA_VERSION
    ):
        return "needs_schema_stamp"

    return "current"


def calculate(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    counts = Counter()

    for row in rows:
        env = environment(row)
        weather = as_dict(
            env.get("weather")
        )

        if env:
            counts["with_environment"] += 1

        if env.get("venue_resolved") is True:
            counts["venue_resolved"] += 1

        if weather:
            counts["with_weather_object"] += 1

        if canonical_schema(weather):
            counts[
                "canonical_weather_schema"
            ] += 1

        # Deliberately independent of schema_version.
        if weather_usable(weather):
            counts["usable_weather"] += 1

        if (
            env.get("schema_version")
            == ENVIRONMENT_SCHEMA_VERSION
        ):
            counts["schema_v2"] += 1

        counts[state(env)] += 1

    total = len(rows)

    def ratio(value: int) -> float:
        return value / total if total else 0.0

    return {
        "total": total,
        **dict(counts),
        "coverage": {
            "environment": ratio(
                counts["with_environment"]
            ),
            "venue_resolved": ratio(
                counts["venue_resolved"]
            ),
            "weather_object": ratio(
                counts["with_weather_object"]
            ),
            "canonical_weather_schema": ratio(
                counts[
                    "canonical_weather_schema"
                ]
            ),
            "usable_weather": ratio(
                counts["usable_weather"]
            ),
            "schema_v2": ratio(
                counts["schema_v2"]
            ),
        },
        "migration": {
            "schema_stamp_only": (
                counts[
                    "needs_schema_stamp"
                ]
            ),
            "real_refresh_needed": (
                counts["missing"]
                + counts["unresolved"]
                + counts["no_weather"]
                + counts[
                    "legacy_weather_schema"
                ]
                + counts[
                    "noncanonical_weather"
                ]
                + counts[
                    "incomplete_weather"
                ]
            ),
        },
    }


def main() -> None:
    repo = SupabaseRepository()

    raw_rows = repo.select_all(
        "matches",
        filters={
            "winner_id": "not.is.null",
        },
        order="scheduled_at.asc",
    )

    canonical_matches = (
        repo.get_completed_matches()
    )

    canonical_rows = [
        {
            "provider_payload": (
                match.provider_payload
            )
        }
        for match in canonical_matches
    ]

    report = {
        "environment_schema_version": (
            ENVIRONMENT_SCHEMA_VERSION
        ),
        "usable_weather_definition": list(
            CORE_WEATHER_FIELDS
        ),
        "raw": calculate(
            raw_rows
        ),
        "canonical": calculate(
            canonical_rows
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
