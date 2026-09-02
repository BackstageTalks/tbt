from __future__ import annotations

import json
from typing import Any

from _bootstrap import ROOT  # noqa: F401

from tbt.repositories.supabase import SupabaseRepository


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("provider_payload")

    return value if isinstance(value, dict) else {}


def _environment_from_row(
    row: dict[str, Any],
) -> dict[str, Any]:
    payload = _payload(row)

    value = payload.get("_tbt_environment")

    return value if isinstance(value, dict) else {}


def _provider_event_id_from_row(
    row: dict[str, Any],
) -> str | None:
    payload = _payload(row)

    for key in (
        "provider_event_id",
        "event_id",
        "eventId",
    ):
        value = payload.get(key)

        if value not in (None, ""):
            return str(value)

    event = payload.get("event")

    if isinstance(event, dict):
        value = event.get("id")

        if value not in (None, ""):
            return str(value)

    value = payload.get("id")

    if value not in (None, ""):
        return str(value)

    return None


def _env_summary(
    env: dict[str, Any],
) -> dict[str, Any]:
    venue = (
        env.get("venue")
        if isinstance(env.get("venue"), dict)
        else {}
    )

    weather = (
        env.get("weather")
        if isinstance(env.get("weather"), dict)
        else {}
    )

    return {
        "venue_resolved": env.get(
            "venue_resolved"
        ),
        "location_query": env.get(
            "location_query"
        ),
        "source": env.get("source"),
        "venue": {
            "name": venue.get("name"),
            "country": venue.get("country"),
            "latitude": venue.get(
                "latitude"
            ),
            "longitude": venue.get(
                "longitude"
            ),
            "elevation_m": venue.get(
                "elevation_m"
            ),
            "timezone": venue.get(
                "timezone"
            ),
        },
        "weather_present": bool(weather),
        "weather": {
            "temperature_2m": weather.get(
                "temperature_2m"
            ),
            "relative_humidity_2m": (
                weather.get(
                    "relative_humidity_2m"
                )
            ),
            "wind_speed_10m": weather.get(
                "wind_speed_10m"
            ),
            "surface_pressure": weather.get(
                "surface_pressure"
            ),
            "weather_code": weather.get(
                "weather_code"
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

    raw_with_env = 0
    raw_resolved = 0
    raw_with_weather = 0

    raw_provider_ids_with_env: set[str] = set()

    examples_raw = []

    for row in raw_rows:
        env = _environment_from_row(row)

        if not env:
            continue

        raw_with_env += 1

        if (
            env.get("venue_resolved")
            is True
        ):
            raw_resolved += 1

        weather = env.get("weather")

        if isinstance(weather, dict) and weather:
            raw_with_weather += 1

        provider_event_id = (
            _provider_event_id_from_row(row)
        )

        if provider_event_id:
            raw_provider_ids_with_env.add(
                provider_event_id
            )

        if len(examples_raw) < 10:
            examples_raw.append(
                {
                    "match_id": row.get(
                        "match_id"
                    ),
                    "scheduled_at": row.get(
                        "scheduled_at"
                    ),
                    "tour": row.get("tour"),
                    "tournament": row.get(
                        "tournament"
                    ),
                    "provider_event_id": (
                        provider_event_id
                    ),
                    "environment": (
                        _env_summary(env)
                    ),
                }
            )

    canonical_with_env = 0
    canonical_resolved = 0
    canonical_with_weather = 0

    canonical_provider_ids_with_env: set[
        str
    ] = set()

    examples_canonical = []
    missing_on_canonical_but_exists_raw = []

    for match in canonical_matches:
        payload = (
            match.provider_payload
            if isinstance(
                match.provider_payload,
                dict,
            )
            else {}
        )

        env = payload.get(
            "_tbt_environment"
        )

        if not isinstance(env, dict):
            env = {}

        provider_event_id = None

        for key in (
            "provider_event_id",
            "event_id",
            "eventId",
        ):
            value = payload.get(key)

            if value not in (None, ""):
                provider_event_id = str(value)
                break

        if provider_event_id is None:
            event = payload.get("event")

            if isinstance(event, dict):
                value = event.get("id")

                if value not in (None, ""):
                    provider_event_id = str(
                        value
                    )

        if provider_event_id is None:
            value = payload.get("id")

            if value not in (None, ""):
                provider_event_id = str(
                    value
                )

        if env:
            canonical_with_env += 1

            if (
                env.get("venue_resolved")
                is True
            ):
                canonical_resolved += 1

            weather = env.get("weather")

            if (
                isinstance(weather, dict)
                and weather
            ):
                canonical_with_weather += 1

            if provider_event_id:
                canonical_provider_ids_with_env.add(
                    provider_event_id
                )

            if len(examples_canonical) < 10:
                examples_canonical.append(
                    {
                        "match_id": (
                            match.match_id
                        ),
                        "scheduled_at": (
                            match.scheduled_at.isoformat()
                        ),
                        "tour": match.tour,
                        "tournament": (
                            match.tournament
                        ),
                        "provider_event_id": (
                            provider_event_id
                        ),
                        "environment": (
                            _env_summary(env)
                        ),
                    }
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
                        match.scheduled_at.isoformat()
                    ),
                    "tour": match.tour,
                    "tournament": (
                        match.tournament
                    ),
                    "provider_event_id": (
                        provider_event_id
                    ),
                }
            )

    report = {
        "raw_completed_rows": len(
            raw_rows
        ),
        "canonical_completed_matches": len(
            canonical_matches
        ),
        "raw": {
            "with_environment": (
                raw_with_env
            ),
            "venue_resolved": (
                raw_resolved
            ),
            "with_weather": (
                raw_with_weather
            ),
            "environment_coverage": (
                raw_with_env
                / len(raw_rows)
                if raw_rows
                else 0.0
            ),
            "resolved_coverage": (
                raw_resolved
                / len(raw_rows)
                if raw_rows
                else 0.0
            ),
            "weather_coverage": (
                raw_with_weather
                / len(raw_rows)
                if raw_rows
                else 0.0
            ),
        },
        "canonical": {
            "with_environment": (
                canonical_with_env
            ),
            "venue_resolved": (
                canonical_resolved
            ),
            "with_weather": (
                canonical_with_weather
            ),
            "environment_coverage": (
                canonical_with_env
                / len(canonical_matches)
                if canonical_matches
                else 0.0
            ),
            "resolved_coverage": (
                canonical_resolved
                / len(canonical_matches)
                if canonical_matches
                else 0.0
            ),
            "weather_coverage": (
                canonical_with_weather
                / len(canonical_matches)
                if canonical_matches
                else 0.0
            ),
        },
        "provider_event_ids": {
            "raw_with_environment": len(
                raw_provider_ids_with_env
            ),
            "canonical_with_environment": len(
                canonical_provider_ids_with_env
            ),
        },
        "missing_on_canonical_but_exists_raw": (
            missing_on_canonical_but_exists_raw
        ),
        "examples_raw": examples_raw,
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
