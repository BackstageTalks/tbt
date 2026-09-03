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
)


logger = logging.getLogger("blinq.environment")

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


def parse_utc(value: str) -> datetime:
    text = value.strip()

    if len(text) == 10:
        text += "T00:00:00+00:00"

    dt = datetime.fromisoformat(
        text.replace("Z", "+00:00")
    )

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt.astimezone(timezone.utc)


def as_dict(
    value: Any,
) -> dict[str, Any]:
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


def canonical_schema(
    weather: dict[str, Any],
) -> bool:
    return all(
        field in weather
        for field in CANONICAL_WEATHER_FIELDS
    )


def usable_weather(
    weather: dict[str, Any],
) -> bool:
    return all(
        safe_number(
            weather.get(field)
        )
        is not None
        for field in CORE_WEATHER_FIELDS
    )


def classify(
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

    if canonical_schema(weather) and usable_weather(weather):
        if (
            env.get("schema_version")
            == ENVIRONMENT_SCHEMA_VERSION
        ):
            return "current"

        return "stamp_only"

    return "refresh"


def main() -> None:
    parser = argparse.ArgumentParser()

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

    args = parser.parse_args()

    start = parse_utc(args.start)
    end = parse_utc(args.end)

    if end <= start:
        raise SystemExit(
            "--end must be later than --start"
        )

    repo = SupabaseRepository()
    client = OpenMeteoClient()

    report = {
        "environment_schema_version": (
            ENVIRONMENT_SCHEMA_VERSION
        ),
        "inspected": 0,
        "already_current": 0,
        "schema_stamped_without_api": 0,
        "external_refreshes": 0,
        "resolved": 0,
        "unresolved": 0,
        "weather_usable": 0,
        "updated": 0,
        "errors": 0,
        "dry_run": args.dry_run,
    }

    try:
        matches = repo.get_matches_between(
            start,
            end,
            completed_only=True,
        )

        if args.limit > 0:
            matches = matches[: args.limit]

        for index, match in enumerate(
            matches,
            start=1,
        ):
            report["inspected"] += 1

            payload = dict(
                match.provider_payload
                or {}
            )

            env = as_dict(
                payload.get(
                    "_tbt_environment"
                )
            )

            state = classify(env)

            if not args.force and state == "current":
                report["already_current"] += 1
                continue

            # Important migration path:
            # good canonical weather already exists.
            # No Open-Meteo request is needed.
            if (
                not args.force
                and state == "stamp_only"
            ):
                env = dict(env)
                env["schema_version"] = (
                    ENVIRONMENT_SCHEMA_VERSION
                )

                payload[
                    "_tbt_environment"
                ] = env

                report[
                    "schema_stamped_without_api"
                ] += 1

                report[
                    "weather_usable"
                ] += 1

                if not args.dry_run:
                    report["updated"] += (
                        repo.update_match_provider_payload(
                            match.match_id,
                            payload,
                        )
                    )

                continue

            try:
                report[
                    "external_refreshes"
                ] += 1

                new_env = environment_payload(
                    client,
                    payload,
                    match.tournament,
                    match.scheduled_at,
                )

                new_env[
                    "schema_version"
                ] = ENVIRONMENT_SCHEMA_VERSION

                payload[
                    "_tbt_environment"
                ] = new_env

                if (
                    new_env.get(
                        "venue_resolved"
                    )
                    is True
                ):
                    report["resolved"] += 1

                    if usable_weather(
                        as_dict(
                            new_env.get(
                                "weather"
                            )
                        )
                    ):
                        report[
                            "weather_usable"
                        ] += 1
                else:
                    report[
                        "unresolved"
                    ] += 1

                if not args.dry_run:
                    report["updated"] += (
                        repo.update_match_provider_payload(
                            match.match_id,
                            payload,
                        )
                    )

            except Exception as exc:
                report["errors"] += 1

                logger.warning(
                    "Environment enrichment failed "
                    "match=%s: %s",
                    match.match_id,
                    exc,
                )

            if (
                args.sleep_ms > 0
                and state != "stamp_only"
            ):
                time.sleep(
                    args.sleep_ms / 1000.0
                )

            if index % 500 == 0:
                logger.info(
                    "Environment %s/%s "
                    "current=%s stamped=%s "
                    "external=%s errors=%s",
                    index,
                    len(matches),
                    report["already_current"],
                    report[
                        "schema_stamped_without_api"
                    ],
                    report["external_refreshes"],
                    report["errors"],
                )

    finally:
        client.close()

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
        level=logging.INFO
    )

    main()
