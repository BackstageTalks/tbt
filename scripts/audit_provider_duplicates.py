# scripts/audit_provider_duplicates.py

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from _bootstrap import ROOT
from tbt.repositories.supabase import SupabaseRepository


REPORT_PATH = ROOT / "reports" / "provider_duplicate_audit.json"
TOP_GROUPS = 100


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("provider_payload")
    return value if isinstance(value, dict) else {}


def _provider_event_id(row: dict[str, Any]) -> str | None:
    # Keep the same extraction logic as the existing data-quality guardrail.
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


def _environment_present(row: dict[str, Any]) -> bool:
    env = _payload(row).get("_tbt_environment")
    return isinstance(env, dict) and bool(env)


def _same_real_match(rows: list[dict[str, Any]]) -> bool:
    """
    Conservative signature:
    - same tour
    - same calendar date
    - same unordered player pair

    Tournament ID is deliberately excluded so we can detect the exact
    duplicate pattern where one real provider event was stored under
    multiple tournament mappings.
    """
    signatures: set[tuple[str, str, tuple[str, str]]] = set()

    for row in rows:
        tour = str(row.get("tour") or "").lower()

        scheduled_at = str(row.get("scheduled_at") or "")
        event_date = scheduled_at[:10]

        player1 = str(row.get("player1_id") or "")
        player2 = str(row.get("player2_id") or "")
        players = tuple(sorted((player1, player2)))

        signatures.add(
            (
                tour,
                event_date,
                players,
            )
        )

    return len(signatures) == 1


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_id": row.get("match_id"),
        "provider_event_id": _provider_event_id(row),
        "scheduled_at": row.get("scheduled_at"),
        "tour": row.get("tour"),
        "tournament": row.get("tournament"),
        "tournament_id": row.get("tournament_id"),
        "tournament_level": row.get("tournament_level"),
        "round_name": row.get("round_name"),
        "player1_id": row.get("player1_id"),
        "player1_name": row.get("player1_name"),
        "player2_id": row.get("player2_id"),
        "player2_name": row.get("player2_name"),
        "winner_id": row.get("winner_id"),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "has_environment": _environment_present(row),
    }


def main() -> None:
    repo = SupabaseRepository()

    # One Supabase read only.
    # No RapidAPI.
    # No Open-Meteo.
    # No INSERT / UPDATE / DELETE.
    all_rows = repo.select_all(
        "matches",
        order="scheduled_at.asc",
    )

    completed_rows = [
        row
        for row in all_rows
        if row.get("winner_id") not in (None, "")
    ]

    provider_groups: dict[
        str,
        list[dict[str, Any]],
    ] = defaultdict(list)

    rows_without_provider_event_id = 0

    for row in completed_rows:
        provider_id = _provider_event_id(row)

        if provider_id is None:
            rows_without_provider_event_id += 1
            continue

        provider_groups[provider_id].append(row)

    duplicate_groups = {
        provider_id: rows
        for provider_id, rows in provider_groups.items()
        if len(rows) > 1
    }

    duplicate_rows_total = sum(
        len(rows)
        for rows in duplicate_groups.values()
    )

    extra_rows = sum(
        len(rows) - 1
        for rows in duplicate_groups.values()
    )

    extra_ratio = (
        extra_rows / len(completed_rows)
        if completed_rows
        else 0.0
    )

    group_size_distribution = Counter(
        len(rows)
        for rows in duplicate_groups.values()
    )

    duplicate_rows_by_year: Counter[str] = Counter()
    duplicate_rows_by_tour: Counter[str] = Counter()

    same_real_match_groups = 0
    conflicting_provider_id_groups = 0

    groups_with_multiple_tournament_ids = 0
    groups_with_multiple_match_ids = 0

    detailed_groups: list[dict[str, Any]] = []

    sorted_groups = sorted(
        duplicate_groups.items(),
        key=lambda item: (
            -len(item[1]),
            item[0],
        ),
    )

    for provider_id, rows in sorted_groups:
        same_real_match = _same_real_match(rows)

        if same_real_match:
            same_real_match_groups += 1
        else:
            conflicting_provider_id_groups += 1

        match_ids = {
            str(row.get("match_id") or "")
            for row in rows
        }

        tournament_ids = {
            str(row.get("tournament_id") or "")
            for row in rows
        }

        tournament_names = {
            str(row.get("tournament") or "")
            for row in rows
        }

        round_names = {
            str(row.get("round_name") or "")
            for row in rows
        }

        if len(match_ids) > 1:
            groups_with_multiple_match_ids += 1

        if len(tournament_ids) > 1:
            groups_with_multiple_tournament_ids += 1

        for row in rows:
            tour = str(
                row.get("tour")
                or "unknown"
            ).lower()

            duplicate_rows_by_tour[tour] += 1

            scheduled_at = str(
                row.get("scheduled_at")
                or ""
            )

            if (
                len(scheduled_at) >= 4
                and scheduled_at[:4].isdigit()
            ):
                duplicate_rows_by_year[
                    scheduled_at[:4]
                ] += 1

        if len(detailed_groups) < TOP_GROUPS:
            detailed_groups.append(
                {
                    "provider_event_id": provider_id,
                    "count": len(rows),
                    "same_real_match_signature": (
                        same_real_match
                    ),
                    "distinct_match_ids": len(
                        match_ids
                    ),
                    "distinct_tournament_ids": len(
                        tournament_ids
                    ),
                    "match_ids": sorted(
                        match_ids
                    ),
                    "tournament_ids": sorted(
                        tournament_ids
                    ),
                    "tournament_names": sorted(
                        tournament_names
                    ),
                    "round_names": sorted(
                        round_names
                    ),
                    "rows": [
                        _compact_row(row)
                        for row in rows
                    ],
                }
            )

    report = {
        "status": "AUDIT_ONLY",
        "read_only": True,
        "description": (
            "Provider-event duplicate diagnostics. "
            "No database writes and no external "
            "TennisApi/Open-Meteo calls."
        ),
        "counts": {
            "all_match_rows": len(
                all_rows
            ),
            "completed_rows": len(
                completed_rows
            ),
            "completed_with_provider_event_id": (
                len(completed_rows)
                - rows_without_provider_event_id
            ),
            "completed_without_provider_event_id": (
                rows_without_provider_event_id
            ),
        },
        "duplicates": {
            "provider_event_duplicate_groups": len(
                duplicate_groups
            ),
            "duplicate_rows_total": (
                duplicate_rows_total
            ),
            "extra_rows_if_deduped": (
                extra_rows
            ),
            "extra_row_ratio": (
                extra_ratio
            ),
            "extra_row_ratio_percent": (
                extra_ratio * 100.0
            ),
            "group_size_distribution": {
                str(size): count
                for size, count
                in sorted(
                    group_size_distribution.items()
                )
            },
        },
        "classification": {
            "same_real_match_signature_groups": (
                same_real_match_groups
            ),
            "conflicting_provider_id_groups": (
                conflicting_provider_id_groups
            ),
            "groups_with_multiple_match_ids": (
                groups_with_multiple_match_ids
            ),
            "groups_with_multiple_tournament_ids": (
                groups_with_multiple_tournament_ids
            ),
        },
        "duplicate_rows_by_tour": dict(
            sorted(
                duplicate_rows_by_tour.items()
            )
        ),
        "duplicate_rows_by_year": dict(
            sorted(
                duplicate_rows_by_year.items()
            )
        ),
        "top_duplicate_groups": (
            detailed_groups
        ),
        "diagnostic_notes": {
            "same_real_match_signature_groups": (
                "Same provider event ID, same tour/date/player pair. "
                "These are very likely duplicate representations "
                "of one real tennis match."
            ),
            "multiple_tournament_ids": (
                "If this number is high, tournament mapping changes "
                "are probably creating different match_id values "
                "for the same provider event."
            ),
            "conflicting_provider_id_groups": (
                "Same provider event ID attached to different "
                "tour/date/player signatures. These require manual "
                "inspection because provider ID extraction or "
                "provider payload may be wrong."
            ),
        },
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
        f"Report written to: "
        f"{REPORT_PATH}"
    )
    print(
        "READ ONLY: no DB rows were modified."
    )

    # Important:
    # duplicates are what we are investigating,
    # therefore this diagnostic workflow must not fail
    # merely because duplicates exist.


if __name__ == "__main__":
    main()
