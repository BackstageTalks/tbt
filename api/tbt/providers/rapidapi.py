from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Iterable

import httpx

from ..config import Settings, settings
from ..errors import ConfigurationError, ProviderError
from ..schemas import MatchRecord
from ..utils import (
    deterministic_id,
    dig,
    first_present,
    normalize_surface,
    parse_datetime,
    safe_float,
    safe_int,
)

logger = logging.getLogger(__name__)


class RapidTennisClient:
    """Tennis provider adapter.

    Canonical match identity is intentionally independent of:
    - provider event ID,
    - tournament/provider table ID,
    - home/away ordering.

    This allows an upcoming fixture and its later historical representation
    to resolve to the same match_id while preventing duplicate rows caused
    by tournament remapping.

    Historical ranking values are deliberately ignored unless a provider
    guarantees point-in-time semantics. This avoids current-ranking leakage
    into historical training data.
    """

    def __init__(self, cfg: Settings = settings) -> None:
        if not cfg.rapidapi_key:
            raise ConfigurationError(
                "RAPIDAPI_KEY is required"
            )

        self.cfg = cfg
        self.client = httpx.Client(
            timeout=cfg.request_timeout_seconds
        )
        self._last_request_at = 0.0

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-RapidAPI-Key": self.cfg.rapidapi_key,
            "X-RapidAPI-Host": self.cfg.rapidapi_host,
            "Accept": "application/json",
            "User-Agent": "TBT-v200/2.0",
        }

    def _throttle(self) -> None:
        elapsed = (
            time.monotonic()
            - self._last_request_at
        )

        if elapsed < 0.66:
            time.sleep(
                0.66 - elapsed
            )

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = (
            f"{self.cfg.rapidapi_base_url}"
            f"{path}"
        )

        last_error: Exception | None = None

        for attempt in range(5):
            self._throttle()

            try:
                response = self.client.get(
                    url,
                    headers=self.headers,
                    params=params or {},
                )

                self._last_request_at = (
                    time.monotonic()
                )

                if response.status_code == 429:
                    delay = float(
                        response.headers.get(
                            "Retry-After",
                            2 + attempt * 2,
                        )
                    )

                    time.sleep(
                        min(
                            max(delay, 1.0),
                            30.0,
                        )
                    )
                    continue

                if response.status_code >= 500:
                    time.sleep(
                        min(
                            2**attempt,
                            15,
                        )
                    )
                    continue

                response.raise_for_status()

                if not response.content:
                    return {}

                return response.json()

            except (
                httpx.HTTPError,
                ValueError,
            ) as exc:
                last_error = exc

                time.sleep(
                    min(
                        2**attempt,
                        10,
                    )
                )

        raise ProviderError(
            f"RapidAPI request failed: "
            f"{path}: {last_error}"
        )

    @staticmethod
    def _data(
        payload: Any,
    ) -> list[dict[str, Any]]:
        if isinstance(
            payload,
            list,
        ):
            return [
                row
                for row in payload
                if isinstance(
                    row,
                    dict,
                )
            ]

        if not isinstance(
            payload,
            dict,
        ):
            return []

        for key in (
            "data",
            "result",
            "results",
            "events",
            "fixtures",
            "matches",
        ):
            value = payload.get(
                key
            )

            if isinstance(
                value,
                list,
            ):
                return [
                    row
                    for row in value
                    if isinstance(
                        row,
                        dict,
                    )
                ]

        return []

    @staticmethod
    def _has_next(
        payload: Any,
    ) -> bool:
        if not isinstance(
            payload,
            dict,
        ):
            return False

        return bool(
            payload.get(
                "hasNextPage"
            )
            or payload.get(
                "has_next_page"
            )
            or dig(
                payload,
                "meta",
                "hasNextPage",
            )
        )

    def _paged(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        page_size: int = 200,
    ) -> list[dict[str, Any]]:
        params = dict(
            params or {}
        )

        params.setdefault(
            "pageSize",
            page_size,
        )

        page = 1

        rows: list[
            dict[str, Any]
        ] = []

        while True:
            params[
                "pageNo"
            ] = page

            payload = self._get(
                path,
                params,
            )

            chunk = self._data(
                payload
            )

            rows.extend(
                chunk
            )

            if (
                not self._has_next(
                    payload
                )
                or not chunk
            ):
                break

            page += 1

            if page > 200:
                raise ProviderError(
                    "Pagination safety "
                    f"limit exceeded for {path}"
                )

        return rows

    def upcoming(
        self,
        tour: str,
        start: date,
        end: date | None = None,
    ) -> list[MatchRecord]:
        tour = tour.lower()

        if tour not in {
            "atp",
            "wta",
        }:
            raise ValueError(
                "tour must be atp or wta"
            )

        if (
            end is None
            or end == start
        ):
            path = (
                f"/tennis/v2/{tour}"
                f"/fixtures/"
                f"{start.isoformat()}"
            )
        else:
            path = (
                f"/tennis/v2/{tour}"
                f"/fixtures/"
                f"{start.isoformat()}/"
                f"{end.isoformat()}"
            )

        rows = self._paged(
            path,
            {
                "include": (
                    "round,tournament,"
                    "tournament.court,"
                    "tournament.rank,"
                    "tournament.country,"
                    "h2h"
                ),
                "filter": (
                    "PlayerGroup:singles"
                ),
            },
        )

        return [
            self.normalize_match(
                row,
                tour=tour,
                historical=False,
            )
            for row in rows
        ]

    def tournament_calendar(
        self,
        tour: str,
        year: int,
    ) -> list[dict[str, Any]]:
        return self._paged(
            (
                f"/tennis/v2/{tour}"
                f"/tournament/calendar/"
                f"{year}"
            ),
            {
                "include": "rating",
                "pageSize": 2000,
            },
            page_size=2000,
        )

    def advanced_calendar(
        self,
        tour: str,
        year: int,
    ) -> list[dict[str, Any]]:
        return self._paged(
            (
                f"/tennis/v2/calendar/"
                f"{tour}/{year}"
            ),
            {
                "pageSize": 200,
            },
            page_size=200,
        )

    def tournament_results(
        self,
        tour: str,
        season_id: str | int,
    ) -> list[MatchRecord]:
        payload = self._get(
            (
                f"/tennis/v2/{tour}"
                f"/tournament/results/"
                f"{season_id}"
            )
        )

        return [
            self.normalize_match(
                row,
                tour=tour,
                historical=True,
            )
            for row in self._data(
                payload
            )
        ]

    @staticmethod
    def _match_richness_score(
        match: MatchRecord,
    ) -> tuple[int, int]:
        payload = (
            match.provider_payload
            if isinstance(
                match.provider_payload,
                dict,
            )
            else {}
        )

        score = 0

        score += int(
            bool(
                match.tournament_id
            )
        )

        score += int(
            bool(
                match.tournament
            )
        )

        score += int(
            bool(
                match.round_name
            )
        )

        score += int(
            bool(
                match.tournament_level
            )
        )

        score += int(
            match.surface
            != "unknown"
        )

        score += int(
            bool(
                match.stats
            )
        )

        score += int(
            match.best_of
            is not None
        )

        score += int(
            match.indoor
            is not None
        )

        score += int(
            match.player1_rank
            is not None
        )

        score += int(
            match.player2_rank
            is not None
        )

        return (
            score,
            len(payload),
        )

    @classmethod
    def _keep_richer_match(
        cls,
        matches: dict[
            str,
            MatchRecord,
        ],
        incoming: MatchRecord,
    ) -> None:
        existing = matches.get(
            incoming.match_id
        )

        if existing is None:
            matches[
                incoming.match_id
            ] = incoming
            return

        if (
            cls._match_richness_score(
                incoming
            )
            > cls._match_richness_score(
                existing
            )
        ):
            matches[
                incoming.match_id
            ] = incoming

    def historical_year(
        self,
        tour: str,
        year: int,
    ) -> list[MatchRecord]:
        matches: dict[
            str,
            MatchRecord,
        ] = {}

        calendar_rows = (
            self.advanced_calendar(
                tour,
                year,
            )
        )

        for node in self._walk_match_nodes(
            calendar_rows
        ):
            match = (
                self.normalize_match(
                    node,
                    tour=tour,
                    historical=True,
                )
            )

            if (
                not match.player1_id
                or not match.player2_id
                or not match.is_completed
            ):
                continue

            self._keep_richer_match(
                matches,
                match,
            )

        if matches:
            logger.info(
                "RapidAPI %s %s: "
                "%s canonical historical "
                "matches from advanced calendar",
                tour,
                year,
                len(matches),
            )

            return sorted(
                matches.values(),
                key=lambda match: (
                    match.scheduled_at,
                    match.match_id,
                ),
            )

        logger.info(
            "Advanced calendar did not expose "
            "match nodes; falling back to "
            "tournament results"
        )

        tournaments = (
            self.tournament_calendar(
                tour,
                year,
            )
        )

        for tournament in tournaments:
            season_id = first_present(
                tournament,
                "seasonid",
                "seasonId",
                "id",
                "tournament_id",
            )

            if season_id in (
                None,
                "",
            ):
                continue

            try:
                for match in (
                    self.tournament_results(
                        tour,
                        season_id,
                    )
                ):
                    if (
                        not match.player1_id
                        or not match.player2_id
                        or not match.is_completed
                    ):
                        continue

                    self._keep_richer_match(
                        matches,
                        match,
                    )

            except ProviderError as exc:
                logger.warning(
                    "Skipping season %s "
                    "after provider error: %s",
                    season_id,
                    exc,
                )

        return sorted(
            matches.values(),
            key=lambda match: (
                match.scheduled_at,
                match.match_id,
            ),
        )

    @classmethod
    def _walk_match_nodes(
        cls,
        value: Any,
    ) -> Iterable[
        dict[str, Any]
    ]:
        if isinstance(
            value,
            list,
        ):
            for item in value:
                yield from (
                    cls._walk_match_nodes(
                        item
                    )
                )

            return

        if not isinstance(
            value,
            dict,
        ):
            return

        keys = {
            str(key).lower()
            for key in value.keys()
        }

        has_p1 = any(
            key in keys
            for key in {
                "player1",
                "player1id",
                "player1_id",
                "participant1",
                "hometeam",
                "home_team",
            }
        )

        has_p2 = any(
            key in keys
            for key in {
                "player2",
                "player2id",
                "player2_id",
                "participant2",
                "awayteam",
                "away_team",
            }
        )

        if (
            has_p1
            and has_p2
        ):
            yield value

        for nested in (
            value.values()
        ):
            if isinstance(
                nested,
                (
                    dict,
                    list,
                ),
            ):
                yield from (
                    cls._walk_match_nodes(
                        nested
                    )
                )

    @staticmethod
    def _player(
        raw: dict[str, Any],
        number: int,
    ) -> tuple[
        str,
        str,
        int | None,
    ]:
        if number == 1:
            object_keys = (
                "player1",
                "participant1",
                "player_1",
                "homeTeam",
                "home_team",
            )

            id_keys = (
                "player1Id",
                "player1_id",
                "participant1Id",
                "homeTeamId",
                "home_team_id",
            )

            name_keys = (
                "player1Name",
                "player1_name",
                "participant1Name",
                "homeTeamName",
                "home_team_name",
            )

            rank_keys = (
                "player1Rank",
                "player1_rank",
                "homeRank",
                "home_rank",
            )

        else:
            object_keys = (
                "player2",
                "participant2",
                "player_2",
                "awayTeam",
                "away_team",
            )

            id_keys = (
                "player2Id",
                "player2_id",
                "participant2Id",
                "awayTeamId",
                "away_team_id",
            )

            name_keys = (
                "player2Name",
                "player2_name",
                "participant2Name",
                "awayTeamName",
                "away_team_name",
            )

            rank_keys = (
                "player2Rank",
                "player2_rank",
                "awayRank",
                "away_rank",
            )

        obj = first_present(
            raw,
            *object_keys,
        )

        player_id = first_present(
            raw,
            *id_keys,
        )

        name = first_present(
            raw,
            *name_keys,
        )

        rank = first_present(
            raw,
            *rank_keys,
        )

        if isinstance(
            obj,
            dict,
        ):
            player_id = (
                player_id
                or first_present(
                    obj,
                    "id",
                    "playerId",
                    "player_id",
                    "key",
                )
            )

            name = (
                name
                or first_present(
                    obj,
                    "name",
                    "playerName",
                    "fullName",
                    "displayName",
                    "shortName",
                )
            )

            rank = (
                rank
                or first_present(
                    obj,
                    "rank",
                    "ranking",
                    "position",
                    "currentRanking",
                )
            )

        elif isinstance(
            obj,
            str,
        ):
            name = (
                name
                or obj
            )

        name = str(
            name
            or f"Player {number}"
        ).strip()

        player_id = str(
            player_id
            or (
                "name:"
                f"{name.lower()}"
            )
        ).strip()

        return (
            player_id,
            name,
            safe_int(
                rank
            ),
        )

    @staticmethod
    def _status_text(
        raw: dict[str, Any],
    ) -> str:
        value = first_present(
            raw,
            "status",
            "state",
        )

        if isinstance(
            value,
            dict,
        ):
            nested = first_present(
                value,
                "type",
                "name",
                "status",
                "state",
                "description",
            )

            return str(
                nested
                or ""
            ).lower()

        return str(
            value
            or ""
        ).lower()

    @staticmethod
    def _winner_id(
        raw: dict[str, Any],
        p1_id: str,
        p2_id: str,
        historical: bool,
        status: str,
        result_text: Any,
    ) -> str | None:
        explicit_winner = (
            first_present(
                raw,
                "winnerId",
                "winner_id",
                "winnerTeamId",
            )
        )

        if explicit_winner not in (
            None,
            "",
        ):
            return str(
                explicit_winner
            )

        winner_code = first_present(
            raw,
            "winnerCode",
            "winner_code",
        )

        if winner_code not in (
            None,
            "",
        ):
            code = str(
                winner_code
            ).strip().lower()

            if code in {
                "1",
                "home",
                "player1",
                "p1",
            }:
                return p1_id

            if code in {
                "2",
                "away",
                "player2",
                "p2",
            }:
                return p2_id

        completed_status = (
            status
            in {
                "completed",
                "complete",
                "ended",
                "finished",
                "final",
                "retired",
                "walkover",
            }
        )

        if (
            historical
            and (
                result_text
                not in (
                    None,
                    "",
                )
                or completed_status
            )
        ):
            return p1_id

        return None

    @staticmethod
    def _stats(
        raw: dict[str, Any],
    ) -> dict[
        str,
        float | None,
    ]:
        stat = first_present(
            raw,
            "stat",
            "stats",
            "statistics",
        )

        if not isinstance(
            stat,
            dict,
        ):
            return {}

        def side_value(
            side: str,
            aliases: tuple[
                str,
                ...,
            ],
        ) -> float | None:
            side_obj = stat.get(
                side
            )

            if isinstance(
                side_obj,
                dict,
            ):
                for alias in aliases:
                    if alias in side_obj:
                        return safe_float(
                            side_obj[
                                alias
                            ]
                        )

            for alias in aliases:
                for key in (
                    f"{side}_{alias}",
                    f"{alias}_{side}",
                ):
                    if key in stat:
                        return safe_float(
                            stat[
                                key
                            ]
                        )

            return None

        result: dict[
            str,
            float | None,
        ] = {}

        aliases = {
            "first_serve_win": (
                "firstServeWon",
                "first_serve_won",
                "win_1st_serve",
                "firstServeWinPct",
            ),
            "second_serve_win": (
                "secondServeWon",
                "second_serve_won",
                "win_2nd_serve",
                "secondServeWinPct",
            ),
            "ace_rate": (
                "aceRate",
                "ace_rate",
                "acesPct",
            ),
            "return_points_won": (
                "returnPointsWon",
                "return_points_won",
                "returnWinPct",
            ),
            "break_points_won": (
                "breakPointsWon",
                "break_points_won",
                "breakPointConversion",
            ),
        }

        for (
            prefix,
            provider_side,
        ) in (
            (
                "p1",
                "player1",
            ),
            (
                "p2",
                "player2",
            ),
        ):
            for (
                canonical,
                names,
            ) in aliases.items():
                result[
                    f"{prefix}_{canonical}"
                ] = side_value(
                    provider_side,
                    names,
                )

        return result

    @classmethod
    def normalize_match(
        cls,
        raw: dict[str, Any],
        tour: str,
        historical: bool,
    ) -> MatchRecord:
        (
            p1_id,
            p1_name,
            p1_rank,
        ) = cls._player(
            raw,
            1,
        )

        (
            p2_id,
            p2_name,
            p2_rank,
        ) = cls._player(
            raw,
            2,
        )

        # Historical ranking snapshots from the provider are not trusted
        # unless their point-in-time semantics are explicitly guaranteed.
        # Dropping them prevents current-ranking leakage into old matches.
        if historical:
            p1_rank = None
            p2_rank = None

        tournament_obj = first_present(
            raw,
            "tournament",
            "tour",
        )

        if not isinstance(
            tournament_obj,
            dict,
        ):
            tournament_obj = {}

        court_obj = first_present(
            tournament_obj,
            "court",
            "surface",
        )

        rank_obj = first_present(
            tournament_obj,
            "rank",
            "level",
            "category",
        )

        surface_value: Any = (
            first_present(
                raw,
                "surface",
                "court",
                "courtName",
                "groundType",
            )
        )

        if isinstance(
            court_obj,
            dict,
        ):
            surface_value = (
                first_present(
                    court_obj,
                    "name",
                    "court_name",
                    "type",
                )
                or surface_value
            )

        elif isinstance(
            court_obj,
            str,
        ):
            surface_value = (
                court_obj
            )

        tournament_ground = first_present(
            tournament_obj,
            "groundType",
            "ground_type",
        )

        if (
            surface_value
            in (
                None,
                "",
            )
            and tournament_ground
            not in (
                None,
                "",
            )
        ):
            surface_value = (
                tournament_ground
            )

        level_value: Any = (
            first_present(
                raw,
                "tournamentLevel",
                "level",
                "rankName",
            )
        )

        if isinstance(
            rank_obj,
            dict,
        ):
            level_value = (
                first_present(
                    rank_obj,
                    "name",
                    "rank_name",
                    "title",
                )
                or level_value
            )

        elif isinstance(
            rank_obj,
            str,
        ):
            level_value = (
                rank_obj
            )

        category_obj = (
            tournament_obj.get(
                "category"
            )
            if isinstance(
                tournament_obj,
                dict,
            )
            else None
        )

        if (
            level_value
            in (
                None,
                "",
            )
            and isinstance(
                category_obj,
                dict,
            )
        ):
            level_value = (
                first_present(
                    category_obj,
                    "name",
                    "slug",
                )
            )

        tournament_name = (
            first_present(
                raw,
                "tournamentName",
                "eventName",
            )
        )

        tournament_id = (
            first_present(
                raw,
                "tournamentId",
                "tourId",
                "seasonId",
                "seasonid",
            )
        )

        if tournament_obj:
            tournament_name = (
                tournament_name
                or first_present(
                    tournament_obj,
                    "name",
                    "tournamentName",
                    "title",
                )
            )

            tournament_id = (
                tournament_id
                or first_present(
                    tournament_obj,
                    "id",
                    "seasonid",
                    "seasonId",
                    "tournamentId",
                )
            )

        scheduled = first_present(
            raw,
            "startTimestamp",
            "startTime",
            "scheduledAt",
            "scheduled_at",
            "date",
            "matchDate",
            "eventDate",
        )

        scheduled_dt = (
            parse_datetime(
                scheduled
            )
        )

        result_text = first_present(
            raw,
            "result",
            "score",
            "finalScore",
        )

        status = cls._status_text(
            raw
        )

        if not status:
            status = (
                "completed"
                if result_text
                not in (
                    None,
                    "",
                )
                else "upcoming"
            )

        winner_id = cls._winner_id(
            raw=raw,
            p1_id=p1_id,
            p2_id=p2_id,
            historical=historical,
            status=status,
            result_text=result_text,
        )

        round_obj = first_present(
            raw,
            "round",
            "roundInfo",
        )

        round_name = first_present(
            raw,
            "roundName",
            "round_name",
        )

        round_id = first_present(
            raw,
            "roundId",
            "round_id",
        )

        if isinstance(
            round_obj,
            dict,
        ):
            round_id = (
                round_id
                or first_present(
                    round_obj,
                    "id",
                    "roundId",
                    "key",
                )
            )

            round_name = (
                round_name
                or first_present(
                    round_obj,
                    "name",
                    "roundName",
                    "title",
                )
            )

        elif isinstance(
            round_obj,
            str,
        ):
            round_name = (
                round_name
                or round_obj
            )

        round_token = str(
            round_id
            or round_name
            or ""
        ).strip().lower()

        player_pair = sorted(
            (
                str(
                    p1_id
                ),
                str(
                    p2_id
                ),
            )
        )

        # Canonical identity deliberately excludes provider event ID and
        # tournament_id. Both were observed to differ across representations
        # of the same real match.
        #
        # Player order is sorted, so home/away or winner-first reordering
        # does not alter identity.
        match_id = deterministic_id(
            [
                tour.lower(),
                scheduled_dt.date().isoformat(),
                player_pair[0],
                player_pair[1],
                round_token,
            ]
        )

        best_of = safe_int(
            first_present(
                raw,
                "bestOf",
                "best_of",
                "setsToPlay",
            )
        )

        indoor_raw = (
            first_present(
                raw,
                "indoor",
                "isIndoor",
            )
        )

        indoor = (
            None
            if indoor_raw is None
            else bool(
                indoor_raw
            )
        )

        surface = normalize_surface(
            surface_value
        )

        if (
            surface
            == "indoor_hard"
        ):
            indoor = True

        return MatchRecord(
            match_id=match_id,
            tour=tour.lower(),
            scheduled_at=scheduled_dt,
            player1_id=p1_id,
            player1_name=p1_name,
            player2_id=p2_id,
            player2_name=p2_name,
            surface=surface,
            tournament=str(
                tournament_name
                or ""
            ),
            tournament_id=str(
                tournament_id
                or ""
            ),
            tournament_level=str(
                level_value
                or ""
            ),
            round_name=str(
                round_name
                or ""
            ),
            player1_rank=p1_rank,
            player2_rank=p2_rank,
            winner_id=winner_id,
            status=status,
            best_of=best_of,
            indoor=indoor,
            stats=cls._stats(
                raw
            ),
            provider_payload=raw,
        )
