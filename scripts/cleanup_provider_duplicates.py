from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from _bootstrap import ROOT
from tbt.providers.rapidapi import RapidTennisClient
from tbt.repositories.supabase import SupabaseRepository
from tbt.utils import deterministic_id, parse_datetime


REPORT_PATH = ROOT / "reports" / "provider_duplicate_cleanup_dry_run.json"
MAX_EXAMPLES = 100


def provider_payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("provider_payload")
    return value if isinstance(value, dict) else {}


def provider_event_id(row: dict[str, Any]) -> str | None:
    payload = provider_payload(row)

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
        for key in (
            "id",
            "eventId",
            "event_id",
        ):
            value = event.get(key)

            if value not in (None, ""):
                return str(value)

    value = payload.get("id")

    if value not in (None, ""):
        return str(value)

    return None


def row_fallback_canonical_id(
    row: dict[str, Any],
) -> str:
    """
    Conservative fallback matching the new identity philosophy:

    tour
    calendar date
    unordered player pair
    round name

    tournament_id and provider event ID are deliberately excluded.
    """

    scheduled_at = parse_datetime(
        row.get("scheduled_at")
    )

    player1_id = str(
        row.get("player1_id") or ""
    )

    player2_id = str(
        row.get("player2_id") or ""
    )

    players = sorted(
        (
            player1_id,
            player2_id,
        )
    )

    round_token = str(
        row.get("round_name") or ""
    ).strip().lower()

    return deterministic_id(
        [
            str(
                row.get("tour") or ""
            ).lower(),
            scheduled_at.date().isoformat(),
            players[0],
            players[1],
            round_token,
        ]
    )


def calculate_canonical_id(
    row: dict[str, Any],
) -> tuple[str, str]:
    """
    First try the current production RapidTennisClient normalization against
    the stored raw provider payload.

    This gives us the exact match_id logic that future ingestion will use.

    If an old payload cannot be normalized, fall back to already-normalized
    DB columns.
    """

    payload = provider_payload(row)

    if payload:
        try:
            normalized = RapidTennisClient.normalize_match(
                payload,
                tour=str(
                    row.get("tour") or ""
                ).lower(),
                historical=True,
            )

            return (
                normalized.match_id,
                "provider_payload",
            )

        except Exception:
            pass

    return (
        row_fallback_canonical_id(
            row
        ),
        "row_fallback",
    )


def environment_present(
    row: dict[str, Any],
) -> bool:
    env = provider_payload(row).get(
        "_tbt_environment"
    )

    return (
        isinstance(env, dict)
        and bool(env)
    )


def row_richness(
    row: dict[str, Any],
) -> tuple[int, int, int, str]:
    """
    Deterministic ranking used ONLY for dry-run planning.

    Prefer:
    1. environment-enriched row
    2. richer normalized metadata
    3. larger provider payload
    4. deterministic match_id tie breaker
    """

    score = 0

    score += 10 * int(
        environment_present(row)
    )

    for key in (
        "tournament_id",
        "tournament",
        "tournament_level",
        "round_name",
        "surface",
        "winner_id",
        "status",
    ):
        if row.get(key) not in (
            None,
            "",
            "unknown",
        ):
            score += 1

    stats = row.get("stats")

    if isinstance(stats, dict):
        populated_stats = sum(
            1
            for value in stats.values()
            if value not in (
                None,
                "",
            )
        )
    else:
        populated_stats = 0

    payload_size = len(
        json.dumps(
            provider_payload(row),
            sort_keys=True,
            default=str,
        )
    )

    return (
        score,
        populated_stats,
        payload_size,
        str(
            row.get("match_id") or ""
        ),
    )


def compact_row(
    row: dict[str, Any],
    target_match_id: str,
    identity_source: str,
) -> dict[str, Any]:
    return {
        "old_match_id": row.get(
            "match_id"
        ),
        "target_match_id": (
            target_match_id
        ),
        "identity_source": (
            identity_source
        ),
        "provider_event_id": (
            provider_event_id(row)
        ),
        "scheduled_at": row.get(
            "scheduled_at"
        ),
        "tour": row.get(
            "tour"
        ),
        "tournament": row.get(
            "tournament"
        ),
        "tournament_id": row.get(
            "tournament_id"
        ),
        "round_name": row.get(
            "round_name"
        ),
        "player1_id": row.get(
            "player1_id"
        ),
        "player1_name": row.get(
            "player1_name"
        ),
        "player2_id": row.get(
            "player2_id"
        ),
        "player2_name": row.get(
            "player2_name"
        ),
        "winner_id": row.get(
            "winner_id"
        ),
        "has_environment": (
            environment_present(row)
        ),
        "richness": list(
            row_richness(row)
        ),
    }


def main() -> None:
    repo = SupabaseRepository()

    print(
        "Loading raw matches from Supabase..."
    )

    rows = repo.select_all(
        "matches",
        order="scheduled_at.asc",
    )

    completed_rows = [
        row
        for row in rows
        if row.get("winner_id")
        not in (
            None,
            "",
        )
    ]

    print(
        f"Raw rows: {len(rows)}"
    )

    print(
        "Completed rows: "
        f"{len(completed_rows)}"
    )

    canonical_groups: dict[
        str,
        list[
            tuple[
                dict[str, Any],
                str,
            ]
        ],
    ] = defaultdict(list)

    identity_source_counts: Counter[
        str
    ] = Counter()

    normalization_errors = 0

    for index, row in enumerate(
        completed_rows,
        start=1,
    ):
        try:
            (
                target_match_id,
                identity_source,
            ) = calculate_canonical_id(
                row
            )

        except Exception as exc:
            normalization_errors += 1

            print(
                "ERROR canonicalizing "
                f"{row.get('match_id')}: "
                f"{exc}"
            )

            continue

        identity_source_counts[
            identity_source
        ] += 1

        canonical_groups[
            target_match_id
        ].append(
            (
                row,
                identity_source,
            )
        )

        if index % 5000 == 0:
            print(
                "Processed "
                f"{index}/"
                f"{len(completed_rows)}"
            )

    duplicate_target_groups = {
        target_id: group
        for target_id, group
        in canonical_groups.items()
        if len(group) > 1
    }

    single_target_groups = {
        target_id: group
        for target_id, group
        in canonical_groups.items()
        if len(group) == 1
    }

    already_canonical_rows = 0
    rows_needing_rekey = 0

    for target_id, group in (
        canonical_groups.items()
    ):
        for row, _ in group:
            if (
                str(
                    row.get(
                        "match_id"
                    )
                    or ""
                )
                == target_id
            ):
                already_canonical_rows += 1
            else:
                rows_needing_rekey += 1

    size_distribution = Counter(
        len(group)
        for group
        in duplicate_target_groups.values()
    )

    provider_ids_per_group: Counter[
        int
    ] = Counter()

    player_signature_conflicts = 0
    winner_conflicts = 0
    scheduled_time_conflicts = 0
    tour_conflicts = 0

    groups_with_environment = 0
    groups_with_multiple_environment_rows = 0

    examples: list[
        dict[str, Any]
    ] = []

    safe_merge_groups = 0
    unsafe_groups = 0

    planned_rows_removed = 0

    for (
        target_id,
        group,
    ) in sorted(
        duplicate_target_groups.items(),
        key=lambda item: (
            -len(item[1]),
            item[0],
        ),
    ):
        rows_only = [
            item[0]
            for item in group
        ]

        provider_ids = {
            provider_event_id(row)
            for row in rows_only
            if provider_event_id(
                row
            )
            is not None
        }

        provider_ids_per_group[
            len(provider_ids)
        ] += 1

        player_signatures = {
            tuple(
                sorted(
                    (
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
                    )
                )
            )
            for row in rows_only
        }

        winners = {
            str(
                row.get(
                    "winner_id"
                )
                or ""
            )
            for row in rows_only
        }

        tours = {
            str(
                row.get(
                    "tour"
                )
                or ""
            ).lower()
            for row in rows_only
        }

        scheduled_times = {
            str(
                row.get(
                    "scheduled_at"
                )
                or ""
            )
            for row in rows_only
        }

        environment_rows = sum(
            1
            for row in rows_only
            if environment_present(
                row
            )
        )

        if environment_rows:
            groups_with_environment += 1

        if environment_rows > 1:
            groups_with_multiple_environment_rows += 1

        conflict_reasons: list[
            str
        ] = []

        if len(
            player_signatures
        ) != 1:
            player_signature_conflicts += 1
            conflict_reasons.append(
                "different_player_pairs"
            )

        if len(
            winners
        ) != 1:
            winner_conflicts += 1
            conflict_reasons.append(
                "different_winners"
            )

        if len(
            tours
        ) != 1:
            tour_conflicts += 1
            conflict_reasons.append(
                "different_tours"
            )

        # Same calendar match may have small schedule changes, therefore
        # differing timestamps are reported but not automatically unsafe.
        if len(
            scheduled_times
        ) != 1:
            scheduled_time_conflicts += 1

        safe = (
            len(
                player_signatures
            )
            == 1
            and len(
                winners
            )
            == 1
            and len(
                tours
            )
            == 1
        )

        if safe:
            safe_merge_groups += 1
            planned_rows_removed += (
                len(group) - 1
            )
        else:
            unsafe_groups += 1

        ranked_rows = sorted(
            rows_only,
            key=row_richness,
            reverse=True,
        )

        keeper = ranked_rows[0]

        if (
            len(examples)
            < MAX_EXAMPLES
        ):
            source_lookup = {
                str(
                    row.get(
                        "match_id"
                    )
                    or ""
                ): source
                for row, source
                in group
            }

            examples.append(
                {
                    "target_match_id": (
                        target_id
                    ),
                    "group_size": len(
                        group
                    ),
                    "safe_to_merge": (
                        safe
                    ),
                    "conflict_reasons": (
                        conflict_reasons
                    ),
                    "provider_event_ids": (
                        sorted(
                            provider_ids
                        )
                    ),
                    "scheduled_times": (
                        sorted(
                            scheduled_times
                        )
                    ),
                    "keeper_old_match_id": (
                        keeper.get(
                            "match_id"
                        )
                    ),
                    "keeper_has_environment": (
                        environment_present(
                            keeper
                        )
                    ),
                    "rows": [
                        compact_row(
                            row,
                            target_id,
                            source_lookup.get(
                                str(
                                    row.get(
                                        "match_id"
                                    )
                                    or ""
                                ),
                                "unknown",
                            ),
                        )
                        for row
                        in ranked_rows
                    ],
                }
            )

    target_ids_existing_as_old_ids = {
        str(
            row.get(
                "match_id"
            )
            or ""
        )
        for row in completed_rows
    }

    target_collision_with_existing = 0

    for target_id, group in (
        canonical_groups.items()
    ):
        old_ids_in_group = {
            str(
                row.get(
                    "match_id"
                )
                or ""
            )
            for row, _
            in group
        }

        if (
            target_id
            in target_ids_existing_as_old_ids
            and target_id
            not in old_ids_in_group
        ):
            target_collision_with_existing += 1

    report = {
        "mode": "DRY_RUN",
        "read_only": True,
        "database_modified": False,
        "summary": {
            "raw_rows": len(
                rows
            ),
            "completed_rows": len(
                completed_rows
            ),
            "canonical_target_groups": len(
                canonical_groups
            ),
            "single_target_groups": len(
                single_target_groups
            ),
            "duplicate_target_groups": len(
                duplicate_target_groups
            ),
            "already_canonical_rows": (
                already_canonical_rows
            ),
            "rows_needing_rekey": (
                rows_needing_rekey
            ),
            "safe_merge_groups": (
                safe_merge_groups
            ),
            "unsafe_groups": (
                unsafe_groups
            ),
            "planned_duplicate_rows_removed": (
                planned_rows_removed
            ),
            "normalization_errors": (
                normalization_errors
            ),
            "target_collision_with_existing": (
                target_collision_with_existing
            ),
        },
        "identity_sources": dict(
            identity_source_counts
        ),
        "duplicate_group_size_distribution": {
            str(size): count
            for size, count
            in sorted(
                size_distribution.items()
            )
        },
        "provider_event_ids_per_duplicate_group": {
            str(size): count
            for size, count
            in sorted(
                provider_ids_per_group.items()
            )
        },
        "conflicts": {
            "player_signature_conflicts": (
                player_signature_conflicts
            ),
            "winner_conflicts": (
                winner_conflicts
            ),
            "tour_conflicts": (
                tour_conflicts
            ),
            "scheduled_time_conflicts": (
                scheduled_time_conflicts
            ),
        },
        "environment": {
            "duplicate_groups_with_environment": (
                groups_with_environment
            ),
            "duplicate_groups_with_multiple_environment_rows": (
                groups_with_multiple_environment_rows
            ),
        },
        "examples": examples,
    }

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    print()
    print(
        json.dumps(
            report["summary"],
            indent=2,
            ensure_ascii=False,
        )
    )

    print()
    print(
        "Conflict summary:"
    )

    print(
        json.dumps(
            report["conflicts"],
            indent=2,
            ensure_ascii=False,
        )
    )

    print()
    print(
        "DRY RUN ONLY."
    )

    print(
        "No INSERT, UPDATE or DELETE "
        "was executed."
    )

    print(
        f"Report: {REPORT_PATH}"
    )

    # Fail the workflow only if the dry-run found something that makes an
    # automatic cleanup unsafe.
    unsafe_conditions = (
        normalization_errors > 0
        or unsafe_groups > 0
        or target_collision_with_existing > 0
    )

    if unsafe_conditions:
        raise SystemExit(
            "Dry-run detected unsafe cleanup conditions. "
            "Database was NOT modified."
        )


if __name__ == "__main__":
    main()
