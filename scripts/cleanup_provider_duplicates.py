from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any, Iterable

from _bootstrap import ROOT
from tbt.providers.rapidapi import RapidTennisClient
from tbt.repositories.supabase import SupabaseRepository
from tbt.utils import deterministic_id, parse_datetime


REPORT_PATH = (
    ROOT
    / "reports"
    / "provider_duplicate_cleanup.json"
)

MATCH_UPSERT_BATCH = 200
MATCH_DELETE_BATCH = 100
PREDICTION_UPSERT_BATCH = 100
PREDICTION_DELETE_BATCH = 100


def payload(
    row: dict[str, Any],
) -> dict[str, Any]:
    value = row.get(
        "provider_payload"
    )

    if isinstance(
        value,
        dict,
    ):
        return value

    return {}


def environment_present(
    row: dict[str, Any],
) -> bool:
    environment = payload(
        row
    ).get(
        "_tbt_environment"
    )

    return (
        isinstance(
            environment,
            dict,
        )
        and bool(
            environment
        )
    )


def fallback_match_id(
    row: dict[str, Any],
) -> str:
    scheduled_at = parse_datetime(
        row.get(
            "scheduled_at"
        )
    )

    player_pair = sorted(
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

    round_token = str(
        row.get(
            "round_name"
        )
        or ""
    ).strip().lower()

    return deterministic_id(
        [
            str(
                row.get(
                    "tour"
                )
                or ""
            ).lower(),
            scheduled_at.date().isoformat(),
            player_pair[0],
            player_pair[1],
            round_token,
        ]
    )


def canonical_match_id(
    row: dict[str, Any],
) -> str:
    raw = payload(
        row
    )

    if raw:
        try:
            normalized = (
                RapidTennisClient
                .normalize_match(
                    raw,
                    tour=str(
                        row.get(
                            "tour"
                        )
                        or ""
                    ).lower(),
                    historical=bool(
                        row.get(
                            "winner_id"
                        )
                    ),
                )
            )

            return (
                normalized.match_id
            )

        except Exception:
            pass

    return fallback_match_id(
        row
    )


def match_richness(
    row: dict[str, Any],
) -> tuple[
    int,
    int,
    int,
    str,
]:
    """
    Choose which representation of the same canonical match survives.

    Environment-enriched rows are strongly preferred so enrichment work
    already stored in provider_payload is preserved.
    """

    score = 0

    if environment_present(
        row
    ):
        score += 1000

    for key in (
        "winner_id",
        "tournament",
        "tournament_id",
        "tournament_level",
        "round_name",
        "surface",
        "status",
        "best_of",
        "indoor",
    ):
        value = row.get(
            key
        )

        if value not in (
            None,
            "",
            "unknown",
        ):
            score += 1

    stats = row.get(
        "stats"
    )

    populated_stats = 0

    if isinstance(
        stats,
        dict,
    ):
        populated_stats = sum(
            1
            for value in stats.values()
            if value not in (
                None,
                "",
            )
        )

    raw_size = len(
        json.dumps(
            payload(
                row
            ),
            sort_keys=True,
            default=str,
        )
    )

    return (
        score,
        populated_stats,
        raw_size,
        str(
            row.get(
                "match_id"
            )
            or ""
        ),
    )


def prediction_richness(
    row: dict[str, Any],
) -> tuple[
    int,
    int,
    str,
]:
    """
    Prefer settled prediction rows over unsettled duplicates.
    """

    score = 0

    if row.get(
        "is_correct"
    ) is not None:
        score += 1000

    if row.get(
        "result_winner_id"
    ) not in (
        None,
        "",
    ):
        score += 500

    for value in row.values():
        if value not in (
            None,
            "",
            {},
            [],
        ):
            score += 1

    raw_size = len(
        json.dumps(
            row,
            sort_keys=True,
            default=str,
        )
    )

    return (
        score,
        raw_size,
        str(
            row.get(
                "match_id"
            )
            or ""
        ),
    )


def sanitize_row(
    row: dict[str, Any],
) -> dict[str, Any]:
    """
    Remove server-managed timestamp columns before an upsert.
    """

    result = dict(
        row
    )

    result.pop(
        "created_at",
        None,
    )

    result.pop(
        "updated_at",
        None,
    )

    return result


def verify_match_group(
    rows: list[
        dict[str, Any]
    ],
) -> list[str]:
    errors: list[
        str
    ] = []

    player_pairs = {
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
        for row in rows
    }

    tours = {
        str(
            row.get(
                "tour"
            )
            or ""
        ).lower()
        for row in rows
    }

    winners = {
        str(
            row.get(
                "winner_id"
            )
        )
        for row in rows
        if row.get(
            "winner_id"
        )
        not in (
            None,
            "",
        )
    }

    if len(
        player_pairs
    ) != 1:
        errors.append(
            "different_player_pairs"
        )

    if len(
        tours
    ) != 1:
        errors.append(
            "different_tours"
        )

    if len(
        winners
    ) > 1:
        errors.append(
            "different_winners"
        )

    return errors


def batched(
    values: list[Any],
    size: int,
) -> Iterable[
    list[Any]
]:
    for start in range(
        0,
        len(values),
        size,
    ):
        yield values[
            start:
            start + size
        ]


def postgrest_in(
    values: list[str],
) -> str:
    """
    Construct PostgREST:
        in.(id1,id2,id3)

    match_id values are deterministic hexadecimal strings, therefore they
    do not require quoting.
    """

    if not values:
        raise ValueError(
            "Cannot build empty IN filter"
        )

    return (
        "in.("
        + ",".join(
            values
        )
        + ")"
    )


def build_match_plan(
    matches: list[
        dict[str, Any]
    ],
) -> tuple[
    dict[str, str],
    list[dict[str, Any]],
    list[str],
    dict[str, Any],
]:
    old_to_new: dict[
        str,
        str,
    ] = {}

    groups: dict[
        str,
        list[
            dict[str, Any]
        ],
    ] = defaultdict(
        list
    )

    for row in matches:
        old_match_id = str(
            row.get(
                "match_id"
            )
            or ""
        )

        if not old_match_id:
            raise RuntimeError(
                "Match row without match_id"
            )

        new_match_id = (
            canonical_match_id(
                row
            )
        )

        old_to_new[
            old_match_id
        ] = new_match_id

        groups[
            new_match_id
        ].append(
            row
        )

    canonical_rows: list[
        dict[str, Any]
    ] = []

    old_ids_to_delete: list[
        str
    ] = []

    duplicate_groups = 0
    duplicate_extra_rows = 0
    unsafe_groups: list[
        dict[str, Any]
    ] = []

    for (
        new_match_id,
        rows,
    ) in groups.items():
        errors = (
            verify_match_group(
                rows
            )
        )

        if errors:
            unsafe_groups.append(
                {
                    "new_match_id": (
                        new_match_id
                    ),
                    "errors": errors,
                    "old_match_ids": [
                        row.get(
                            "match_id"
                        )
                        for row
                        in rows
                    ],
                }
            )

            continue

        if len(
            rows
        ) > 1:
            duplicate_groups += 1
            duplicate_extra_rows += (
                len(rows) - 1
            )

        keeper = max(
            rows,
            key=match_richness,
        )

        canonical = sanitize_row(
            keeper
        )

        canonical[
            "match_id"
        ] = new_match_id

        canonical_rows.append(
            canonical
        )

        for row in rows:
            old_match_id = str(
                row.get(
                    "match_id"
                )
                or ""
            )

            if (
                old_match_id
                != new_match_id
            ):
                old_ids_to_delete.append(
                    old_match_id
                )

    if unsafe_groups:
        raise RuntimeError(
            "Unsafe canonical match groups detected: "
            + json.dumps(
                unsafe_groups[:20],
                default=str,
            )
        )

    existing_ids = {
        str(
            row.get(
                "match_id"
            )
            or ""
        )
        for row in matches
    }

    source_ids_by_target = {
        target: {
            str(
                row.get(
                    "match_id"
                )
                or ""
            )
            for row in rows
        }
        for target, rows
        in groups.items()
    }

    target_collisions = []

    for target in groups:
        if (
            target in existing_ids
            and target
            not in source_ids_by_target[
                target
            ]
        ):
            target_collisions.append(
                target
            )

    if target_collisions:
        raise RuntimeError(
            "Canonical target IDs collide "
            "with unrelated existing rows: "
            f"{target_collisions[:20]}"
        )

    summary = {
        "raw_match_rows": len(
            matches
        ),
        "canonical_match_rows": len(
            canonical_rows
        ),
        "duplicate_groups": (
            duplicate_groups
        ),
        "duplicate_extra_rows": (
            duplicate_extra_rows
        ),
        "match_ids_needing_rekey": sum(
            1
            for old_id, new_id
            in old_to_new.items()
            if old_id != new_id
        ),
        "old_match_rows_to_delete": len(
            old_ids_to_delete
        ),
        "unsafe_match_groups": 0,
        "target_collisions": 0,
    }

    return (
        old_to_new,
        canonical_rows,
        old_ids_to_delete,
        summary,
    )


def build_prediction_plan(
    predictions: list[
        dict[str, Any]
    ],
    old_to_new: dict[
        str,
        str,
    ],
) -> tuple[
    list[dict[str, Any]],
    list[str],
    dict[str, Any],
]:
    groups: dict[
        tuple[
            str,
            str,
        ],
        list[
            dict[str, Any]
        ],
    ] = defaultdict(
        list
    )

    missing_match_ids: list[
        str
    ] = []

    old_prediction_match_ids: list[
        str
    ] = []

    for row in predictions:
        old_match_id = str(
            row.get(
                "match_id"
            )
            or ""
        )

        model_version = str(
            row.get(
                "model_version"
            )
            or ""
        )

        if not old_match_id:
            raise RuntimeError(
                "Prediction without match_id"
            )

        if not model_version:
            raise RuntimeError(
                "Prediction without model_version"
            )

        new_match_id = (
            old_to_new.get(
                old_match_id
            )
        )

        if not new_match_id:
            missing_match_ids.append(
                old_match_id
            )

            continue

        groups[
            (
                new_match_id,
                model_version,
            )
        ].append(
            row
        )

        if (
            old_match_id
            != new_match_id
        ):
            old_prediction_match_ids.append(
                old_match_id
            )

    if missing_match_ids:
        raise RuntimeError(
            "Predictions reference matches "
            "outside migration plan: "
            f"{missing_match_ids[:20]}"
        )

    canonical_rows: list[
        dict[str, Any]
    ] = []

    collision_groups = 0
    collision_extra_rows = 0

    for (
        (
            new_match_id,
            model_version,
        ),
        rows,
    ) in groups.items():
        if len(
            rows
        ) > 1:
            collision_groups += 1
            collision_extra_rows += (
                len(rows) - 1
            )

        settled_results = {
            (
                str(
                    row.get(
                        "result_winner_id"
                    )
                    or ""
                ),
                row.get(
                    "is_correct"
                ),
            )
            for row in rows
            if (
                row.get(
                    "result_winner_id"
                )
                not in (
                    None,
                    "",
                )
                or row.get(
                    "is_correct"
                )
                is not None
            )
        }

        if len(
            settled_results
        ) > 1:
            raise RuntimeError(
                "Conflicting settled predictions "
                f"for {new_match_id} / "
                f"{model_version}: "
                f"{settled_results}"
            )

        predicted_winners = {
            str(
                row.get(
                    "predicted_winner_id"
                )
                or ""
            )
            for row in rows
        }

        if len(
            predicted_winners
        ) > 1:
            raise RuntimeError(
                "Duplicate prediction rows disagree "
                "on predicted winner for "
                f"{new_match_id} / "
                f"{model_version}: "
                f"{predicted_winners}"
            )

        keeper = max(
            rows,
            key=prediction_richness,
        )

        canonical = sanitize_row(
            keeper
        )

        canonical[
            "match_id"
        ] = new_match_id

        canonical[
            "model_version"
        ] = model_version

        canonical_rows.append(
            canonical
        )

    summary = {
        "raw_prediction_rows": len(
            predictions
        ),
        "canonical_prediction_rows": len(
            canonical_rows
        ),
        "prediction_collision_groups": (
            collision_groups
        ),
        "prediction_collision_extra_rows": (
            collision_extra_rows
        ),
        "prediction_rows_needing_rekey": len(
            old_prediction_match_ids
        ),
    }

    return (
        canonical_rows,
        sorted(
            set(
                old_prediction_match_ids
            )
        ),
        summary,
    )


def delete_by_match_ids(
    repo: SupabaseRepository,
    table: str,
    match_ids: list[str],
    batch_size: int,
) -> int:
    total = 0

    unique_ids = sorted(
        set(
            match_ids
        )
    )

    for index, chunk in enumerate(
        batched(
            unique_ids,
            batch_size,
        ),
        start=1,
    ):
        total += repo.delete(
            table,
            {
                "match_id": (
                    postgrest_in(
                        chunk
                    )
                )
            },
        )

        if index % 50 == 0:
            print(
                f"{table}: delete batches "
                f"{index}"
            )

    return total


def execute_migration(
    repo: SupabaseRepository,
    canonical_matches: list[
        dict[str, Any]
    ],
    canonical_predictions: list[
        dict[str, Any]
    ],
    old_prediction_match_ids: list[
        str
    ],
    old_match_ids: list[
        str
    ],
) -> dict[str, int]:
    stats = {
        "canonical_matches_upserted": 0,
        "canonical_predictions_upserted": 0,
        "old_predictions_deleted": 0,
        "old_matches_deleted": 0,
    }

    print()
    print(
        "STEP 1/6 - Upserting canonical matches"
    )

    match_batches = list(
        batched(
            canonical_matches,
            MATCH_UPSERT_BATCH,
        )
    )

    for index, chunk in enumerate(
        match_batches,
        start=1,
    ):
        stats[
            "canonical_matches_upserted"
        ] += repo.upsert(
            "matches",
            chunk,
            "match_id",
        )

        if (
            index % 25 == 0
            or index == len(
                match_batches
            )
        ):
            print(
                "Match upsert batches: "
                f"{index}/"
                f"{len(match_batches)}"
            )

    print()
    print(
        "STEP 2/6 - Upserting canonical predictions"
    )

    for chunk in batched(
        canonical_predictions,
        PREDICTION_UPSERT_BATCH,
    ):
        stats[
            "canonical_predictions_upserted"
        ] += repo.upsert(
            "predictions",
            chunk,
            "match_id,model_version",
        )

    print()
    print(
        "STEP 3/6 - Deleting old prediction rows"
    )

    stats[
        "old_predictions_deleted"
    ] = delete_by_match_ids(
        repo=repo,
        table="predictions",
        match_ids=(
            old_prediction_match_ids
        ),
        batch_size=(
            PREDICTION_DELETE_BATCH
        ),
    )

    print()
    print(
        "STEP 4/6 - Verifying predictions no longer "
        "reference old match IDs"
    )

    predictions_after = (
        repo.select_all(
            "predictions"
        )
    )

    old_match_id_set = set(
        old_match_ids
    )

    remaining_old_predictions = [
        row
        for row in predictions_after
        if str(
            row.get(
                "match_id"
            )
            or ""
        )
        in old_match_id_set
    ]

    if remaining_old_predictions:
        raise RuntimeError(
            "Refusing to delete old matches: "
            f"{len(remaining_old_predictions)} "
            "predictions still reference old IDs."
        )

    print()
    print(
        "STEP 5/6 - Deleting old match rows"
    )

    stats[
        "old_matches_deleted"
    ] = delete_by_match_ids(
        repo=repo,
        table="matches",
        match_ids=(
            old_match_ids
        ),
        batch_size=(
            MATCH_DELETE_BATCH
        ),
    )

    print()
    print(
        "STEP 6/6 - Write phase completed"
    )

    return stats


def verify_database(
    repo: SupabaseRepository,
) -> dict[str, Any]:
    print()
    print(
        "Reloading database for final verification..."
    )

    matches = repo.select_all(
        "matches",
        order="scheduled_at.asc",
    )

    predictions = repo.select_all(
        "predictions"
    )

    match_ids = [
        str(
            row.get(
                "match_id"
            )
            or ""
        )
        for row in matches
    ]

    duplicate_match_primary_keys = (
        len(match_ids)
        - len(
            set(
                match_ids
            )
        )
    )

    mismatched_canonical_ids = 0

    recalculated_ids: list[
        str
    ] = []

    for row in matches:
        expected = (
            canonical_match_id(
                row
            )
        )

        recalculated_ids.append(
            expected
        )

        if (
            expected
            != str(
                row.get(
                    "match_id"
                )
                or ""
            )
        ):
            mismatched_canonical_ids += 1

    duplicate_canonical_matches = (
        len(
            recalculated_ids
        )
        - len(
            set(
                recalculated_ids
            )
        )
    )

    prediction_keys = [
        (
            str(
                row.get(
                    "match_id"
                )
                or ""
            ),
            str(
                row.get(
                    "model_version"
                )
                or ""
            ),
        )
        for row in predictions
    ]

    duplicate_prediction_keys = (
        len(
            prediction_keys
        )
        - len(
            set(
                prediction_keys
            )
        )
    )

    existing_match_ids = set(
        match_ids
    )

    orphan_predictions = sum(
        1
        for row in predictions
        if str(
            row.get(
                "match_id"
            )
            or ""
        )
        not in existing_match_ids
    )

    verification = {
        "match_rows": len(
            matches
        ),
        "prediction_rows": len(
            predictions
        ),
        "duplicate_match_primary_keys": (
            duplicate_match_primary_keys
        ),
        "mismatched_canonical_match_ids": (
            mismatched_canonical_ids
        ),
        "duplicate_canonical_matches": (
            duplicate_canonical_matches
        ),
        "duplicate_prediction_keys": (
            duplicate_prediction_keys
        ),
        "orphan_predictions": (
            orphan_predictions
        ),
    }

    if any(
        (
            duplicate_match_primary_keys,
            mismatched_canonical_ids,
            duplicate_canonical_matches,
            duplicate_prediction_keys,
            orphan_predictions,
        )
    ):
        raise RuntimeError(
            "Final verification failed: "
            + json.dumps(
                verification,
                default=str,
            )
        )

    return verification


def write_report(
    report: dict[str, Any],
) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Canonical match-ID migration "
            "with provider-duplicate cleanup."
        )
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually modify Supabase. "
            "Without --apply this script "
            "is strictly read-only."
        ),
    )

    args = parser.parse_args()

    repo = SupabaseRepository()

    print(
        "Loading matches..."
    )

    matches = repo.select_all(
        "matches",
        order="scheduled_at.asc",
    )

    print(
        f"Loaded match rows: "
        f"{len(matches)}"
    )

    print(
        "Loading predictions..."
    )

    predictions = repo.select_all(
        "predictions"
    )

    print(
        f"Loaded prediction rows: "
        f"{len(predictions)}"
    )

    (
        old_to_new,
        canonical_matches,
        old_match_ids,
        match_summary,
    ) = build_match_plan(
        matches
    )

    (
        canonical_predictions,
        old_prediction_match_ids,
        prediction_summary,
    ) = build_prediction_plan(
        predictions,
        old_to_new,
    )

    report: dict[
        str,
        Any,
    ] = {
        "mode": (
            "APPLY"
            if args.apply
            else "DRY_RUN"
        ),
        "database_modified": False,
        "match_plan": (
            match_summary
        ),
        "prediction_plan": (
            prediction_summary
        ),
        "expected_after": {
            "match_rows": len(
                canonical_matches
            ),
            "prediction_rows": len(
                canonical_predictions
            ),
        },
        "write_stats": None,
        "verification": None,
    }

    print()
    print(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )

    if not args.apply:
        write_report(
            report
        )

        print()
        print(
            "DRY RUN ONLY."
        )

        print(
            "No INSERT, UPDATE or DELETE "
            "was executed."
        )

        return

    print()
    print(
        "======================================"
    )

    print(
        "APPLY MODE ENABLED"
    )

    print(
        "======================================"
    )

    write_stats = (
        execute_migration(
            repo=repo,
            canonical_matches=(
                canonical_matches
            ),
            canonical_predictions=(
                canonical_predictions
            ),
            old_prediction_match_ids=(
                old_prediction_match_ids
            ),
            old_match_ids=(
                old_match_ids
            ),
        )
    )

    report[
        "database_modified"
    ] = True

    report[
        "write_stats"
    ] = write_stats

    verification = (
        verify_database(
            repo
        )
    )

    report[
        "verification"
    ] = verification

    write_report(
        report
    )

    print()
    print(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )

    print()
    print(
        "======================================"
    )

    print(
        "CANONICAL MIGRATION COMPLETED"
    )

    print(
        "======================================"
    )


if __name__ == "__main__":
    main()
