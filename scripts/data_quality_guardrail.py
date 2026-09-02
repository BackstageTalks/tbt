from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from _bootstrap import ROOT

from tbt.repositories.supabase import SupabaseRepository


MIN_CANONICAL_COMPLETED = 10_000
MAX_FUTURE_COMPLETED_DAYS = 2
MAX_DUPLICATE_EXTRA_RATIO = 0.05
MAX_MISSING_PLAYER_RATIO = 0.001
MAX_INVALID_WINNER_RATIO = 0.001


VALID_TOURS = {
    "atp",
    "wta",
}


VALID_SURFACES = {
    "hard",
    "clay",
    "grass",
    "indoor_hard",
    "carpet",
    "unknown",
}


def _payload(
    row: dict[str, Any],
) -> dict[str, Any]:
    value = row.get(
        "provider_payload"
    )

    return (
        value
        if isinstance(value, dict)
        else {}
    )


def _provider_event_id(
    row: dict[str, Any],
) -> str | None:
    payload = _payload(row)

    for key in (
        "provider_event_id",
        "event_id",
        "eventId",
    ):
        value = payload.get(key)

        if value not in (
            None,
            "",
        ):
            return str(value)

    event = payload.get(
        "event"
    )

    if isinstance(event, dict):
        value = event.get(
            "id"
        )

        if value not in (
            None,
            "",
        ):
            return str(value)

    value = payload.get(
        "id"
    )

    if value not in (
        None,
        "",
    ):
        return str(value)

    return None


def _environment(
    row: dict[str, Any],
) -> dict[str, Any]:
    payload = _payload(row)

    value = payload.get(
        "_tbt_environment"
    )

    return (
        value
        if isinstance(value, dict)
        else {}
    )


def _weather_present(
    env: dict[str, Any],
) -> bool:
    weather = env.get(
        "weather"
    )

    return (
        isinstance(weather, dict)
        and bool(weather)
    )


def _parse_dt(
    value: Any,
) -> datetime | None:
    if value in (
        None,
        "",
    ):
        return None

    try:
        text = str(value).replace(
            "Z",
            "+00:00",
        )

        parsed = (
            datetime.fromisoformat(
                text
            )
        )

        if (
            parsed.tzinfo
            is None
        ):
            parsed = (
                parsed.replace(
                    tzinfo=timezone.utc
                )
            )

        return parsed.astimezone(
            timezone.utc
        )

    except (
        TypeError,
        ValueError,
    ):
        return None


def _ratio(
    numerator: int,
    denominator: int,
) -> float:
    if denominator <= 0:
        return 0.0

    return (
        numerator
        / denominator
    )


def main() -> None:
    repo = (
        SupabaseRepository()
    )

    now = datetime.now(
        timezone.utc
    )

    all_rows = repo.select_all(
        "matches",
        order="scheduled_at.asc",
    )

    raw_completed = [
        row
        for row in all_rows
        if row.get(
            "winner_id"
        )
        not in (
            None,
            "",
        )
    ]

    canonical_completed = (
        repo.get_completed_matches()
    )

    warnings: list[str] = []
    failures: list[str] = []

    # -------------------------------------------------
    # Core row counts
    # -------------------------------------------------

    total_rows = len(
        all_rows
    )

    raw_completed_count = len(
        raw_completed
    )

    canonical_completed_count = len(
        canonical_completed
    )

    if (
        canonical_completed_count
        < MIN_CANONICAL_COMPLETED
    ):
        failures.append(
            "Canonical completed history "
            f"too small: "
            f"{canonical_completed_count} "
            f"< {MIN_CANONICAL_COMPLETED}"
        )

    # -------------------------------------------------
    # Missing IDs
    # -------------------------------------------------

    missing_player1 = sum(
        1
        for row in raw_completed
        if row.get(
            "player1_id"
        )
        in (
            None,
            "",
        )
    )

    missing_player2 = sum(
        1
        for row in raw_completed
        if row.get(
            "player2_id"
        )
        in (
            None,
            "",
        )
    )

    missing_player_any = sum(
        1
        for row in raw_completed
        if (
            row.get(
                "player1_id"
            )
            in (
                None,
                "",
            )
            or row.get(
                "player2_id"
            )
            in (
                None,
                "",
            )
        )
    )

    missing_player_ratio = (
        _ratio(
            missing_player_any,
            raw_completed_count,
        )
    )

    if (
        missing_player_ratio
        > MAX_MISSING_PLAYER_RATIO
    ):
        failures.append(
            "Too many completed matches "
            "with missing player IDs: "
            f"{missing_player_any}/"
            f"{raw_completed_count} "
            f"({missing_player_ratio:.4%})"
        )

    # -------------------------------------------------
    # Winner sanity
    # -------------------------------------------------

    invalid_winner_rows = []

    for row in raw_completed:
        winner_id = str(
            row.get(
                "winner_id"
            )
            or ""
        )

        player1_id = str(
            row.get(
                "player1_id"
            )
            or ""
        )

        player2_id = str(
            row.get(
                "player2_id"
            )
            or ""
        )

        if (
            winner_id
            and winner_id
            not in {
                player1_id,
                player2_id,
            }
        ):
            if (
                len(
                    invalid_winner_rows
                )
                < 20
            ):
                invalid_winner_rows.append(
                    {
                        "match_id": row.get(
                            "match_id"
                        ),
                        "winner_id": (
                            winner_id
                        ),
                        "player1_id": (
                            player1_id
                        ),
                        "player2_id": (
                            player2_id
                        ),
                    }
                )

    invalid_winner_count = len(
        [
            row
            for row in raw_completed
            if (
                str(
                    row.get(
                        "winner_id"
                    )
                    or ""
                )
                not in {
                    str(
                        row.get(
                            "player1_id"
                        )
                        or ""
                    ),
                    str(
                        row.get(
                            "player2_id"
                        )
                        or ""
                    ),
                }
            )
        ]
    )

    invalid_winner_ratio = (
        _ratio(
            invalid_winner_count,
            raw_completed_count,
        )
    )

    if (
        invalid_winner_ratio
        > MAX_INVALID_WINNER_RATIO
    ):
        failures.append(
            "Too many invalid winner IDs: "
            f"{invalid_winner_count}/"
            f"{raw_completed_count} "
            f"({invalid_winner_ratio:.4%})"
        )

    # -------------------------------------------------
    # Duplicate provider event IDs
    # -------------------------------------------------

    provider_groups: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for row in raw_completed:
        provider_id = (
            _provider_event_id(
                row
            )
        )

        if provider_id:
            provider_groups[
                provider_id
            ].append(
                row
            )

    duplicate_groups = {
        provider_id: rows
        for (
            provider_id,
            rows,
        )
        in provider_groups.items()
        if len(rows) > 1
    }

    duplicate_rows_total = sum(
        len(rows)
        for rows
        in duplicate_groups.values()
    )

    duplicate_extra_rows = sum(
        len(rows) - 1
        for rows
        in duplicate_groups.values()
    )

    duplicate_extra_ratio = (
        _ratio(
            duplicate_extra_rows,
            raw_completed_count,
        )
    )

    if (
        duplicate_extra_ratio
        > MAX_DUPLICATE_EXTRA_RATIO
    ):
        failures.append(
            "Raw duplicate provider-event "
            "ratio too high: "
            f"{duplicate_extra_ratio:.4%}"
        )

    elif (
        duplicate_extra_rows
        > 0
    ):
        warnings.append(
            "Raw provider-event duplicates "
            f"exist: {duplicate_extra_rows} "
            "extra rows. This is acceptable "
            "only while canonical repository "
            "dedupe removes them."
        )

    duplicate_examples = []

    for (
        provider_id,
        rows,
    ) in list(
        duplicate_groups.items()
    )[:10]:
        duplicate_examples.append(
            {
                "provider_event_id": (
                    provider_id
                ),
                "count": len(rows),
                "match_ids": [
                    row.get(
                        "match_id"
                    )
                    for row
                    in rows
                ],
            }
        )

    # -------------------------------------------------
    # Date sanity
    # -------------------------------------------------

    invalid_dates = []
    future_completed = []

    future_limit = (
        now
        + timedelta(
            days=MAX_FUTURE_COMPLETED_DAYS
        )
    )

    for row in raw_completed:
        scheduled = _parse_dt(
            row.get(
                "scheduled_at"
            )
        )

        if scheduled is None:
            if (
                len(
                    invalid_dates
                )
                < 20
            ):
                invalid_dates.append(
                    row.get(
                        "match_id"
                    )
                )

            continue

        if (
            scheduled
            > future_limit
        ):
            if (
                len(
                    future_completed
                )
                < 20
            ):
                future_completed.append(
                    {
                        "match_id": row.get(
                            "match_id"
                        ),
                        "scheduled_at": (
                            scheduled.isoformat()
                        ),
                    }
                )

    if invalid_dates:
        failures.append(
            "Completed rows with invalid "
            f"scheduled_at: "
            f"{len(invalid_dates)}+"
        )

    if future_completed:
        failures.append(
            "Completed matches dated more "
            "than "
            f"{MAX_FUTURE_COMPLETED_DAYS} "
            "days in the future: "
            f"{len(future_completed)}+"
        )

    # -------------------------------------------------
    # Tour sanity
    # -------------------------------------------------

    tour_counter = Counter(
        str(
            row.get(
                "tour"
            )
            or ""
        ).lower()
        for row
        in raw_completed
    )

    invalid_tours = {
        tour: count
        for (
            tour,
            count,
        )
        in tour_counter.items()
        if tour
        not in VALID_TOURS
    }

    if invalid_tours:
        warnings.append(
            "Unexpected tour values exist: "
            f"{invalid_tours}"
        )

    # -------------------------------------------------
    # Surface sanity
    # -------------------------------------------------

    surface_counter = Counter(
        str(
            row.get(
                "surface"
            )
            or "unknown"
        ).lower()
        for row
        in raw_completed
    )

    invalid_surfaces = {
        surface: count
        for (
            surface,
            count,
        )
        in surface_counter.items()
        if surface
        not in VALID_SURFACES
    }

    if invalid_surfaces:
        warnings.append(
            "Unexpected surface values exist: "
            f"{invalid_surfaces}"
        )

    # -------------------------------------------------
    # Environment coverage - raw
    # -------------------------------------------------

    raw_env_count = 0
    raw_weather_count = 0
    raw_resolved_count = 0

    for row in raw_completed:
        env = _environment(
            row
        )

        if not env:
            continue

        raw_env_count += 1

        if (
            env.get(
                "venue_resolved"
            )
            is True
        ):
            raw_resolved_count += 1

        if _weather_present(
            env
        ):
            raw_weather_count += 1

    # -------------------------------------------------
    # Environment coverage - canonical
    # -------------------------------------------------

    canonical_env_count = 0
    canonical_weather_count = 0
    canonical_resolved_count = 0

    for match in canonical_completed:
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

        if not isinstance(
            env,
            dict,
        ):
            continue

        if not env:
            continue

        canonical_env_count += 1

        if (
            env.get(
                "venue_resolved"
            )
            is True
        ):
            canonical_resolved_count += 1

        if _weather_present(
            env
        ):
            canonical_weather_count += 1

    canonical_env_coverage = (
        _ratio(
            canonical_env_count,
            canonical_completed_count,
        )
    )

    canonical_weather_coverage = (
        _ratio(
            canonical_weather_count,
            canonical_completed_count,
        )
    )

    if (
        canonical_env_coverage
        < 0.70
    ):
        warnings.append(
            "Canonical environment coverage "
            "is below challenger threshold: "
            f"{canonical_env_coverage:.2%}"
        )

    # -------------------------------------------------
    # Canonical reduction sanity
    # -------------------------------------------------

    canonical_reduction = (
        raw_completed_count
        - canonical_completed_count
    )

    if (
        canonical_reduction
        < 0
    ):
        failures.append(
            "Canonical completed count is "
            "larger than raw completed count."
        )

    # -------------------------------------------------
    # Final report
    # -------------------------------------------------

    status = (
        "FAIL"
        if failures
        else (
            "WARN"
            if warnings
            else "PASS"
        )
    )

    report = {
        "status": status,
        "generated_at": (
            now.isoformat()
        ),
        "thresholds": {
            "min_canonical_completed": (
                MIN_CANONICAL_COMPLETED
            ),
            "max_future_completed_days": (
                MAX_FUTURE_COMPLETED_DAYS
            ),
            "max_duplicate_extra_ratio": (
                MAX_DUPLICATE_EXTRA_RATIO
            ),
            "max_missing_player_ratio": (
                MAX_MISSING_PLAYER_RATIO
            ),
            "max_invalid_winner_ratio": (
                MAX_INVALID_WINNER_RATIO
            ),
            "environment_challenger_threshold": (
                0.70
            ),
        },
        "counts": {
            "all_rows": (
                total_rows
            ),
            "raw_completed": (
                raw_completed_count
            ),
            "canonical_completed": (
                canonical_completed_count
            ),
            "canonical_reduction": (
                canonical_reduction
            ),
        },
        "players": {
            "missing_player1_id": (
                missing_player1
            ),
            "missing_player2_id": (
                missing_player2
            ),
            "missing_any_player_id": (
                missing_player_any
            ),
            "missing_ratio": (
                missing_player_ratio
            ),
        },
        "winners": {
            "invalid_winner_count": (
                invalid_winner_count
            ),
            "invalid_winner_ratio": (
                invalid_winner_ratio
            ),
            "examples": (
                invalid_winner_rows
            ),
        },
        "duplicates": {
            "provider_event_duplicate_groups": (
                len(
                    duplicate_groups
                )
            ),
            "duplicate_rows_total": (
                duplicate_rows_total
            ),
            "extra_rows": (
                duplicate_extra_rows
            ),
            "extra_ratio": (
                duplicate_extra_ratio
            ),
            "examples": (
                duplicate_examples
            ),
        },
        "dates": {
            "invalid_scheduled_at_examples": (
                invalid_dates
            ),
            "future_completed_examples": (
                future_completed
            ),
        },
        "tour_counts": dict(
            sorted(
                tour_counter.items()
            )
        ),
        "unexpected_tours": (
            invalid_tours
        ),
        "surface_counts": dict(
            sorted(
                surface_counter.items()
            )
        ),
        "unexpected_surfaces": (
            invalid_surfaces
        ),
        "environment": {
            "raw": {
                "with_environment": (
                    raw_env_count
                ),
                "venue_resolved": (
                    raw_resolved_count
                ),
                "with_weather": (
                    raw_weather_count
                ),
                "environment_coverage": (
                    _ratio(
                        raw_env_count,
                        raw_completed_count,
                    )
                ),
                "weather_coverage": (
                    _ratio(
                        raw_weather_count,
                        raw_completed_count,
                    )
                ),
            },
            "canonical": {
                "with_environment": (
                    canonical_env_count
                ),
                "venue_resolved": (
                    canonical_resolved_count
                ),
                "with_weather": (
                    canonical_weather_count
                ),
                "environment_coverage": (
                    canonical_env_coverage
                ),
                "weather_coverage": (
                    canonical_weather_coverage
                ),
            },
        },
        "warnings": warnings,
        "failures": failures,
    }

    report_path = (
        ROOT
        / "reports"
        / "data_quality_guardrail.json"
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )

    if failures:
        raise SystemExit(
            "Data quality guardrail FAILED"
        )


if __name__ == "__main__":
    main()
