from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
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

# Do not SELECT * from the growing matches table.
# These are the only columns required for:
# - environment coverage
# - provider-event canonical dedupe
# - repository-equivalent canonical priority
AUDIT_SELECT = ",".join(
    (
        "match_id",
        "scheduled_at",
        "tour",
        "tournament",
        "tournament_id",
        "round_name",
        "winner_id",
        "stats",
        "provider_payload",
    )
)

# provider_payload can be large because it now also contains
# environment/weather data. Keep pages intentionally small.
AUDIT_PAGE_SIZE = 200


def as_dict(
    value: Any,
) -> dict[str, Any]:
    return (
        value
        if isinstance(value, dict)
        else {}
    )


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


def payload(
    row: dict[str, Any],
) -> dict[str, Any]:
    return as_dict(
        row.get("provider_payload")
    )


def environment(
    row: dict[str, Any],
) -> dict[str, Any]:
    return as_dict(
        payload(row).get(
            "_tbt_environment"
        )
    )


def provider_event_id(
    row: dict[str, Any],
) -> str | None:
    """
    Extract the real provider event ID using the same precedence
    used by the current canonical repository.
    """
    raw = payload(row)

    for key in (
        "_tbt_provider_event_id",
        "provider_event_id",
        "event_id",
        "eventId",
    ):
        value = raw.get(key)

        if value not in (
            None,
            "",
        ):
            return str(value)

    event = raw.get("event")

    if isinstance(event, dict):
        value = event.get("id")

        if value not in (
            None,
            "",
        ):
            return str(value)

    value = raw.get("id")

    if value not in (
        None,
        "",
    ):
        return str(value)

    return None


def state(
    env: dict[str, Any],
) -> str:
    if not env:
        return "missing"

    if (
        env.get("venue_resolved")
        is not True
    ):
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
            counts[
                "with_environment"
            ] += 1

        if (
            env.get("venue_resolved")
            is True
        ):
            counts[
                "venue_resolved"
            ] += 1

        if weather:
            counts[
                "with_weather_object"
            ] += 1

        if canonical_schema(weather):
            counts[
                "canonical_weather_schema"
            ] += 1

        # Deliberately independent of schema_version.
        #
        # This tells us whether the actual weather values are
        # usable by the model even if only the metadata stamp
        # still needs migration.
        if weather_usable(weather):
            counts[
                "usable_weather"
            ] += 1

        if (
            env.get("schema_version")
            == ENVIRONMENT_SCHEMA_VERSION
        ):
            counts[
                "schema_v2"
            ] += 1

        counts[
            state(env)
        ] += 1

    total = len(rows)

    def ratio(
        value: int,
    ) -> float:
        return (
            value / total
            if total
            else 0.0
        )

    return {
        "total": total,
        **dict(counts),
        "coverage": {
            "environment": ratio(
                counts[
                    "with_environment"
                ]
            ),
            "venue_resolved": ratio(
                counts[
                    "venue_resolved"
                ]
            ),
            "weather_object": ratio(
                counts[
                    "with_weather_object"
                ]
            ),
            "canonical_weather_schema": (
                ratio(
                    counts[
                        "canonical_weather_schema"
                    ]
                )
            ),
            "usable_weather": ratio(
                counts[
                    "usable_weather"
                ]
            ),
            "schema_v2": ratio(
                counts[
                    "schema_v2"
                ]
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


def canonical_priority(
    row: dict[str, Any],
) -> tuple[
    int,
    int,
    int,
    int,
    str,
]:
    """
    Mirror SupabaseRepository._canonical_match_priority().

    When the same real provider event exists under multiple
    database match IDs, choose the richest/current representation.
    """
    raw = payload(row)

    source_category_id = raw.get(
        "_tbt_source_category_id"
    )

    tournament = (
        raw.get("tournament")
        if isinstance(
            raw.get("tournament"),
            dict,
        )
        else {}
    )

    unique_tournament = (
        tournament.get(
            "uniqueTournament"
        )
        if isinstance(
            tournament.get(
                "uniqueTournament"
            ),
            dict,
        )
        else {}
    )

    richness = sum(
        int(bool(value))
        for value in (
            source_category_id,
            unique_tournament.get(
                "id"
            ),
            unique_tournament.get(
                "name"
            ),
            tournament.get(
                "id"
            ),
            tournament.get(
                "name"
            ),
            row.get(
                "tournament_id"
            ),
            row.get(
                "round_name"
            ),
            row.get(
                "stats"
            ),
        )
    )

    try:
        payload_size = len(
            json.dumps(
                raw,
                ensure_ascii=False,
                default=str,
            )
        )

    except Exception:
        payload_size = 0

    return (
        int(
            source_category_id
            is not None
        ),
        int(
            bool(
                unique_tournament.get(
                    "id"
                )
            )
        ),
        richness,
        payload_size,
        str(
            row.get("match_id")
            or ""
        ),
    )


def dedupe_completed_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Canonical completed-match dedupe.

    Only rows sharing the same real provider event ID are
    collapsed.

    Rows without a provider event ID remain untouched.

    This intentionally mirrors the repository behaviour without
    doing another full-table Supabase query.
    """
    grouped: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    without_provider_id: list[
        dict[str, Any]
    ] = []

    for row in rows:
        event_id = provider_event_id(
            row
        )

        if event_id is None:
            without_provider_id.append(
                row
            )
            continue

        grouped[
            event_id
        ].append(
            row
        )

    canonical: list[
        dict[str, Any]
    ] = []

    for group in grouped.values():
        if len(group) == 1:
            canonical.append(
                group[0]
            )
            continue

        winner = max(
            group,
            key=canonical_priority,
        )

        canonical.append(
            winner
        )

    canonical.extend(
        without_provider_id
    )

    # The audit itself does not need SQL chronological sorting.
    # Sorting locally is cheap and deterministic.
    canonical.sort(
        key=lambda row: (
            str(
                row.get(
                    "scheduled_at"
                )
                or ""
            ),
            str(
                row.get(
                    "match_id"
                )
                or ""
            ),
        )
    )

    return canonical


def main() -> None:
    repo = (
        SupabaseRepository()
    )

    # -------------------------------------------------
    # ONE Supabase snapshot only
    # -------------------------------------------------
    #
    # Previous implementation:
    #
    # 1. select=* completed rows ordered by scheduled_at
    # 2. repo.get_completed_matches()
    #    -> another select=* ordered by scheduled_at
    #
    # At the current DB size that produces PostgreSQL
    # statement_timeout (57014).
    #
    # New implementation:
    #
    # - filter completed rows server-side
    # - fetch only required columns
    # - page by match_id
    # - canonical dedupe locally
    #
    raw_rows = repo.select_all(
        "matches",
        filters={
            "winner_id": (
                "not.is.null"
            ),
        },
        select=AUDIT_SELECT,
        order="match_id.asc",
        page_size=AUDIT_PAGE_SIZE,
    )

    canonical_rows = (
        dedupe_completed_rows(
            raw_rows
        )
    )

    raw_report = calculate(
        raw_rows
    )

    canonical_report = calculate(
        canonical_rows
    )

    duplicate_rows_ignored = (
        len(raw_rows)
        - len(canonical_rows)
    )

    report = {
        "environment_schema_version": (
            ENVIRONMENT_SCHEMA_VERSION
        ),
        "usable_weather_definition": list(
            CORE_WEATHER_FIELDS
        ),
        "query_strategy": {
            "single_supabase_snapshot": (
                True
            ),
            "completed_filter_server_side": (
                True
            ),
            "select_star": False,
            "paging_order": (
                "match_id.asc"
            ),
            "page_size": (
                AUDIT_PAGE_SIZE
            ),
            "canonical_dedupe": (
                "local provider-event dedupe "
                "mirroring repository priority"
            ),
        },
        "duplicates": {
            "raw_completed_rows": (
                len(raw_rows)
            ),
            "canonical_completed_rows": (
                len(canonical_rows)
            ),
            "duplicate_rows_ignored": (
                duplicate_rows_ignored
            ),
            "duplicate_ratio": (
                duplicate_rows_ignored
                / len(raw_rows)
                if raw_rows
                else 0.0
            ),
        },
        "raw": (
            raw_report
        ),
        "canonical": (
            canonical_report
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
