from __future__ import annotations

import json
from collections import defaultdict
from datetime import timezone

from _bootstrap import ROOT  # noqa: F401

from tbt.repositories.supabase import SupabaseRepository


def _provider_event_id(match) -> str | None:
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}

    for key in ("id", "eventId", "event_id", "provider_event_id"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)

    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    value = event.get("id")
    return str(value) if value not in (None, "") else None


def _fallback_key(match) -> str:
    day = match.scheduled_at.astimezone(timezone.utc).date().isoformat()
    players = sorted((str(match.player1_id), str(match.player2_id)))

    return f"{match.tour.lower()}|{day}|{players[0]}|{players[1]}"


def _priority(match) -> tuple:
    payload = match.provider_payload if isinstance(match.provider_payload, dict) else {}

    source_category = payload.get("_tbt_source_category_id")

    tournament = (
        payload.get("tournament")
        if isinstance(payload.get("tournament"), dict)
        else {}
    )

    unique = (
        tournament.get("uniqueTournament")
        if isinstance(tournament.get("uniqueTournament"), dict)
        else {}
    )

    richness = sum(
        int(bool(value))
        for value in (
            source_category,
            unique.get("id"),
            unique.get("name"),
            tournament.get("id"),
            tournament.get("name"),
            match.tournament_id,
            match.round_name,
            match.stats,
        )
    )

    return (
        int(source_category is not None),
        int(bool(unique.get("id"))),
        richness,
        len(json.dumps(payload, ensure_ascii=False, default=str)),
        str(match.match_id),
    )


def main() -> None:
    repo = SupabaseRepository()
    matches = repo.get_completed_matches()

    provider_groups = defaultdict(list)
    fallback_groups = defaultdict(list)

    for match in matches:
        event_id = _provider_event_id(match)

        if event_id:
            provider_groups[event_id].append(match)
        else:
            fallback_groups[_fallback_key(match)].append(match)

    duplicate_groups = []

    def add_group(kind: str, key: str, group: list) -> None:
        if len(group) < 2:
            return

        ranked = sorted(group, key=_priority, reverse=True)
        canonical = ranked[0]

        duplicate_groups.append(
            {
                "kind": kind,
                "key": key,
                "count": len(group),
                "canonical_match_id": canonical.match_id,
                "rows": [
                    {
                        "match_id": match.match_id,
                        "scheduled_at": match.scheduled_at.isoformat(),
                        "tour": match.tour,
                        "tournament": match.tournament,
                        "tournament_id": match.tournament_id,
                        "round_name": match.round_name,
                        "player1": match.player1_name,
                        "player2": match.player2_name,
                        "provider_event_id": _provider_event_id(match),
                        "source_category_id": (
                            match.provider_payload.get("_tbt_source_category_id")
                            if isinstance(match.provider_payload, dict)
                            else None
                        ),
                        "priority": _priority(match),
                    }
                    for match in ranked
                ],
            }
        )

    for key, group in provider_groups.items():
        add_group("provider_event_id", key, group)

    for key, group in fallback_groups.items():
        add_group("fallback_pair_day", key, group)

    duplicate_groups.sort(
        key=lambda group: (
            -group["count"],
            group["kind"],
            group["key"],
        )
    )

    report = {
        "completed_matches": len(matches),
        "duplicate_groups": len(duplicate_groups),
        "duplicate_rows_total": sum(
            group["count"]
            for group in duplicate_groups
        ),
        "extra_rows_if_deduped": sum(
            group["count"] - 1
            for group in duplicate_groups
        ),
        "groups": duplicate_groups,
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
