from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from _bootstrap import ROOT
from tbt.providers.rapidapi import RapidTennisClient
from tbt.repositories.supabase import SupabaseRepository
from tbt.utils import deterministic_id, parse_datetime


REPORT_PATH = (
    ROOT
    / "reports"
    / "match_id_dependency_audit.json"
)


def _payload(
    row: dict[str, Any],
) -> dict[str, Any]:
    value = row.get(
        "provider_payload"
    )

    return (
        value
        if isinstance(
            value,
            dict,
        )
        else {}
    )


def _fallback_match_id(
    row: dict[str, Any],
) -> str:
    scheduled_at = parse_datetime(
        row.get(
            "scheduled_at"
        )
    )

    players = sorted(
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
            players[0],
            players[1],
            round_token,
        ]
    )


def _canonical_match_id(
    row: dict[str, Any],
) -> str:
    payload = _payload(
        row
    )

    if payload:
        try:
            match = (
                RapidTennisClient
                .normalize_match(
                    payload,
                    tour=str(
                        row.get(
                            "tour"
                        )
                        or ""
                    ).lower(),
                    historical=True,
                )
            )

            return (
                match.match_id
            )

        except Exception:
            pass

    return _fallback_match_id(
        row
    )


def main() -> None:
    repo = (
        SupabaseRepository()
    )

    print(
        "Loading matches..."
    )

    matches = repo.select_all(
        "matches",
        order="scheduled_at.asc",
    )

    old_to_new: dict[
        str,
        str,
    ] = {}

    new_to_old: dict[
        str,
        list[str],
    ] = defaultdict(
        list
    )

    for row in matches:
        old_id = str(
            row.get(
                "match_id"
            )
            or ""
        )

        if not old_id:
            continue

        new_id = (
            _canonical_match_id(
                row
            )
        )

        old_to_new[
            old_id
        ] = new_id

        new_to_old[
            new_id
        ].append(
            old_id
        )

    print(
        "Loading predictions..."
    )

    predictions = (
        repo.select_all(
            "predictions"
        )
    )

    predictions_on_old_ids = 0
    predictions_already_new = 0
    predictions_missing_match = 0

    affected_prediction_rows: list[
        dict[str, Any]
    ] = []

    collision_keys: dict[
        tuple[str, str],
        list[dict[str, Any]],
    ] = defaultdict(
        list
    )

    existing_match_ids = {
        str(
            row.get(
                "match_id"
            )
            or ""
        )
        for row in matches
    }

    for prediction in predictions:
        old_id = str(
            prediction.get(
                "match_id"
            )
            or ""
        )

        model_version = str(
            prediction.get(
                "model_version"
            )
            or ""
        )

        if (
            old_id
            in old_to_new
        ):
            new_id = (
                old_to_new[
                    old_id
                ]
            )

            if (
                new_id
                != old_id
            ):
                predictions_on_old_ids += 1

                if (
                    len(
                        affected_prediction_rows
                    )
                    < 100
                ):
                    affected_prediction_rows.append(
                        {
                            "old_match_id": (
                                old_id
                            ),
                            "new_match_id": (
                                new_id
                            ),
                            "model_version": (
                                model_version
                            ),
                            "scheduled_at": (
                                prediction.get(
                                    "scheduled_at"
                                )
                            ),
                            "predicted_winner_id": (
                                prediction.get(
                                    "predicted_winner_id"
                                )
                            ),
                            "is_correct": (
                                prediction.get(
                                    "is_correct"
                                )
                            ),
                        }
                    )

            else:
                predictions_already_new += 1

            collision_keys[
                (
                    new_id,
                    model_version,
                )
            ].append(
                prediction
            )

        elif (
            old_id
            not in existing_match_ids
        ):
            predictions_missing_match += 1

    collisions = {
        key: rows
        for key, rows
        in collision_keys.items()
        if len(rows) > 1
    }

    collision_examples = []

    for (
        (
            new_match_id,
            model_version,
        ),
        rows,
    ) in list(
        collisions.items()
    )[:100]:
        collision_examples.append(
            {
                "new_match_id": (
                    new_match_id
                ),
                "model_version": (
                    model_version
                ),
                "count": len(
                    rows
                ),
                "old_match_ids": sorted(
                    {
                        str(
                            row.get(
                                "match_id"
                            )
                            or ""
                        )
                        for row in rows
                    }
                ),
            }
        )

    report = {
        "mode": (
            "READ_ONLY"
        ),
        "database_modified": (
            False
        ),
        "matches": {
            "rows": len(
                matches
            ),
            "old_match_ids": len(
                old_to_new
            ),
            "canonical_match_ids": len(
                new_to_old
            ),
            "match_ids_needing_change": sum(
                1
                for old_id, new_id
                in old_to_new.items()
                if old_id
                != new_id
            ),
        },
        "predictions": {
            "rows": len(
                predictions
            ),
            "rows_using_old_match_id": (
                predictions_on_old_ids
            ),
            "rows_already_using_new_match_id": (
                predictions_already_new
            ),
            "rows_with_missing_match": (
                predictions_missing_match
            ),
            "post_rekey_unique_key_collisions": (
                len(
                    collisions
                )
            ),
        },
        "affected_prediction_examples": (
            affected_prediction_rows
        ),
        "collision_examples": (
            collision_examples
        ),
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
        "READ ONLY."
    )

    print(
        "No database rows were modified."
    )

    if collisions:
        raise SystemExit(
            "Prediction collisions detected. "
            "Do not run match cleanup yet."
        )


if __name__ == "__main__":
    main()
