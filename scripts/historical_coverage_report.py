from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from _bootstrap import ROOT
from tbt.repositories.supabase import SupabaseRepository


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _has_stats(stats: Any) -> bool:
    if not isinstance(stats, dict):
        return False

    for value in stats.values():
        if value not in (None, "", {}, [], 0, 0.0):
            return True

    return False


def _has_environment(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False

    env = payload.get("_tbt_environment")
    return isinstance(env, dict) and bool(env)


def _has_weather(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False

    env = payload.get("_tbt_environment")

    if not isinstance(env, dict):
        return False

    weather = env.get("weather")

    return isinstance(weather, dict) and bool(weather)


def main() -> None:
    repo = SupabaseRepository()

    matches = repo.get_completed_matches()

    by_year: dict[int, list[Any]] = defaultdict(list)

    for match in matches:
        year = match.scheduled_at.astimezone(
            timezone.utc
        ).year

        by_year[year].append(match)

    report_years: dict[str, Any] = {}

    for year in sorted(by_year):
        year_matches = by_year[year]

        total = len(year_matches)

        tours = Counter(
            str(match.tour or "unknown").lower()
            for match in year_matches
        )

        surfaces = Counter(
            str(match.surface or "unknown").lower()
            for match in year_matches
        )

        players: set[str] = set()

        rank_both = 0
        rank_any = 0
        stats_count = 0
        environment_count = 0
        weather_count = 0

        first_date = None
        last_date = None

        for match in year_matches:
            if match.player1_id:
                players.add(
                    f"{match.tour}:{match.player1_id}"
                )

            if match.player2_id:
                players.add(
                    f"{match.tour}:{match.player2_id}"
                )

            p1_rank_known = (
                match.player1_rank is not None
                and match.player1_rank > 0
            )

            p2_rank_known = (
                match.player2_rank is not None
                and match.player2_rank > 0
            )

            if p1_rank_known or p2_rank_known:
                rank_any += 1

            if p1_rank_known and p2_rank_known:
                rank_both += 1

            if _has_stats(match.stats):
                stats_count += 1

            if _has_environment(
                match.provider_payload
            ):
                environment_count += 1

            if _has_weather(
                match.provider_payload
            ):
                weather_count += 1

            scheduled = (
                match.scheduled_at
                .astimezone(timezone.utc)
            )

            if (
                first_date is None
                or scheduled < first_date
            ):
                first_date = scheduled

            if (
                last_date is None
                or scheduled > last_date
            ):
                last_date = scheduled

        atp = tours.get("atp", 0)
        wta = tours.get("wta", 0)

        report_years[str(year)] = {
            "matches": total,
            "atp": atp,
            "wta": wta,
            "atp_share": _ratio(
                atp,
                total,
            ),
            "wta_share": _ratio(
                wta,
                total,
            ),
            "unique_players": len(players),
            "surfaces": dict(
                sorted(
                    surfaces.items()
                )
            ),
            "ranking": {
                "both_players_known": (
                    rank_both
                ),
                "any_player_known": (
                    rank_any
                ),
                "both_players_coverage": (
                    _ratio(
                        rank_both,
                        total,
                    )
                ),
                "any_player_coverage": (
                    _ratio(
                        rank_any,
                        total,
                    )
                ),
            },
            "stats": {
                "with_stats": stats_count,
                "coverage": _ratio(
                    stats_count,
                    total,
                ),
            },
            "environment": {
                "with_environment": (
                    environment_count
                ),
                "coverage": _ratio(
                    environment_count,
                    total,
                ),
                "with_weather": (
                    weather_count
                ),
                "weather_coverage": (
                    _ratio(
                        weather_count,
                        total,
                    )
                ),
            },
            "date_range": {
                "first_match": (
                    first_date.isoformat()
                    if first_date
                    else None
                ),
                "last_match": (
                    last_date.isoformat()
                    if last_date
                    else None
                ),
            },
        }

    year_counts = {
        int(year): data["matches"]
        for year, data
        in report_years.items()
    }

    warnings: list[str] = []

    sorted_years = sorted(
        year_counts
    )

    for index, year in enumerate(
        sorted_years
    ):
        count = year_counts[year]

        if count < 1000:
            warnings.append(
                f"{year}: only {count} "
                "canonical completed matches"
            )

        if index == 0:
            continue

        previous_year = (
            sorted_years[index - 1]
        )

        previous_count = (
            year_counts[
                previous_year
            ]
        )

        if previous_count <= 0:
            continue

        delta_ratio = (
            count
            / previous_count
        )

        if delta_ratio < 0.65:
            warnings.append(
                f"{year}: match count is "
                f"{delta_ratio:.1%} of "
                f"{previous_year}; "
                "possible incomplete year"
            )

    total_matches = len(matches)

    report = {
        "generated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "canonical_completed_matches": (
            total_matches
        ),
        "years_present": sorted_years,
        "year_count": len(
            sorted_years
        ),
        "years": report_years,
        "warnings": warnings,
    }

    path = (
        ROOT
        / "reports"
        / "historical_coverage.json"
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
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


if __name__ == "__main__":
    main()
