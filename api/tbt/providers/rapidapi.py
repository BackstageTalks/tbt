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
    """Adapter for Tennis API – ATP/WTA/ITF on RapidAPI.

    The provider's historical archive uses winner-first ordering. That convention is
    normalized into `winner_id`; the feature engine later randomizes training orientation
    to prevent target leakage.
    """

    def __init__(self, cfg: Settings = settings) -> None:
        if not cfg.rapidapi_key:
            raise ConfigurationError("RAPIDAPI_KEY is required")
        self.cfg = cfg
        self.client = httpx.Client(timeout=cfg.request_timeout_seconds)
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
        # Official docs currently state 100 requests/minute/IP. Stay below that globally.
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < 0.66:
            time.sleep(0.66 - elapsed)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.cfg.rapidapi_base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(5):
            self._throttle()
            try:
                response = self.client.get(url, headers=self.headers, params=params or {})
                self._last_request_at = time.monotonic()
                if response.status_code == 429:
                    delay = float(response.headers.get("Retry-After", 2 + attempt * 2))
                    time.sleep(min(max(delay, 1.0), 30.0))
                    continue
                if response.status_code >= 500:
                    time.sleep(min(2**attempt, 15))
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                time.sleep(min(2**attempt, 10))
        raise ProviderError(f"RapidAPI request failed: {path}: {last_error}")

    @staticmethod
    def _data(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("data", "result", "results", "fixtures", "matches"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        return []

    @staticmethod
    def _has_next(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        return bool(
            payload.get("hasNextPage")
            or payload.get("has_next_page")
            or dig(payload, "meta", "hasNextPage")
        )

    def _paged(self, path: str, params: dict[str, Any] | None = None, page_size: int = 200) -> list[dict[str, Any]]:
        params = dict(params or {})
        params.setdefault("pageSize", page_size)
        page = 1
        rows: list[dict[str, Any]] = []
        while True:
            params["pageNo"] = page
            payload = self._get(path, params)
            chunk = self._data(payload)
            rows.extend(chunk)
            if not self._has_next(payload) or not chunk:
                break
            page += 1
            if page > 200:
                raise ProviderError(f"Pagination safety limit exceeded for {path}")
        return rows

    def upcoming(self, tour: str, start: date, end: date | None = None) -> list[MatchRecord]:
        tour = tour.lower()
        if tour not in {"atp", "wta"}:
            raise ValueError("tour must be atp or wta")
        if end is None or end == start:
            path = f"/tennis/v2/{tour}/fixtures/{start.isoformat()}"
        else:
            path = f"/tennis/v2/{tour}/fixtures/{start.isoformat()}/{end.isoformat()}"
        rows = self._paged(
            path,
            {
                "include": "round,tournament,tournament.court,tournament.rank,tournament.country,h2h",
                "filter": "PlayerGroup:singles",
            },
        )
        return [self.normalize_match(row, tour=tour, historical=False) for row in rows]

    def tournament_calendar(self, tour: str, year: int) -> list[dict[str, Any]]:
        return self._paged(
            f"/tennis/v2/{tour}/tournament/calendar/{year}",
            {"include": "rating", "pageSize": 2000},
            page_size=2000,
        )

    def advanced_calendar(self, tour: str, year: int) -> list[dict[str, Any]]:
        return self._paged(
            f"/tennis/v2/calendar/{tour}/{year}",
            {"pageSize": 200},
            page_size=200,
        )

    def tournament_results(self, tour: str, season_id: str | int) -> list[MatchRecord]:
        payload = self._get(f"/tennis/v2/{tour}/tournament/results/{season_id}")
        return [
            self.normalize_match(row, tour=tour, historical=True)
            for row in self._data(payload)
        ]

    def historical_year(self, tour: str, year: int) -> list[MatchRecord]:
        """Fetch a full historical year with request-efficient calendar-first strategy.

        The advanced calendar can contain matches nested inside tournament objects. If a
        provider plan does not include nested matches, fall back to tournament season IDs
        and fetch each season's results.
        """
        matches: dict[str, MatchRecord] = {}
        calendar_rows = self.advanced_calendar(tour, year)
        for node in self._walk_match_nodes(calendar_rows):
            match = self.normalize_match(node, tour=tour, historical=True)
            if match.player1_id and match.player2_id and match.is_completed:
                matches[match.match_id] = match

        if matches:
            logger.info("RapidAPI %s %s: %s historical matches from advanced calendar", tour, year, len(matches))
            return sorted(matches.values(), key=lambda m: m.scheduled_at)

        logger.info("Advanced calendar did not expose match nodes; falling back to tournament results")
        tournaments = self.tournament_calendar(tour, year)
        for tournament in tournaments:
            season_id = first_present(tournament, "seasonid", "seasonId", "id", "tournament_id")
            if season_id in (None, ""):
                continue
            try:
                for match in self.tournament_results(tour, season_id):
                    matches[match.match_id] = match
            except ProviderError as exc:
                logger.warning("Skipping season %s after provider error: %s", season_id, exc)
        return sorted(matches.values(), key=lambda m: m.scheduled_at)

    @classmethod
    def _walk_match_nodes(cls, value: Any) -> Iterable[dict[str, Any]]:
        if isinstance(value, list):
            for item in value:
                yield from cls._walk_match_nodes(item)
            return
        if not isinstance(value, dict):
            return
        keys = {str(k).lower() for k in value.keys()}
        has_p1 = any(k in keys for k in {"player1", "player1id", "player1_id", "participant1"})
        has_p2 = any(k in keys for k in {"player2", "player2id", "player2_id", "participant2"})
        if has_p1 and has_p2:
            yield value
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                yield from cls._walk_match_nodes(nested)

    @staticmethod
    def _player(raw: dict[str, Any], number: int) -> tuple[str, str, int | None]:
        obj = first_present(
            raw,
            f"player{number}",
            f"participant{number}",
            f"player_{number}",
        )
        player_id = first_present(
            raw,
            f"player{number}Id",
            f"player{number}_id",
            f"participant{number}Id",
        )
        name = first_present(
            raw,
            f"player{number}Name",
            f"player{number}_name",
            f"participant{number}Name",
        )
        rank = first_present(raw, f"player{number}Rank", f"player{number}_rank")
        if isinstance(obj, dict):
            player_id = player_id or first_present(obj, "id", "playerId", "player_id", "key")
            name = name or first_present(obj, "name", "playerName", "fullName", "displayName")
            rank = rank or first_present(obj, "rank", "ranking", "position")
        elif isinstance(obj, str):
            name = name or obj
        # IDs are preferable; stable name fallback keeps the pipeline usable if a plan omits IDs.
        name = str(name or f"Player {number}").strip()
        player_id = str(player_id or f"name:{name.lower()}").strip()
        return player_id, name, safe_int(rank)

    @staticmethod
    def _stats(raw: dict[str, Any]) -> dict[str, float | None]:
        stat = first_present(raw, "stat", "stats", "statistics")
        if not isinstance(stat, dict):
            return {}

        def side_value(side: str, aliases: tuple[str, ...]) -> float | None:
            side_obj = stat.get(side)
            if isinstance(side_obj, dict):
                for alias in aliases:
                    if alias in side_obj:
                        return safe_float(side_obj[alias])
            for alias in aliases:
                for key in (f"{side}_{alias}", f"{alias}_{side}"):
                    if key in stat:
                        return safe_float(stat[key])
            return None

        result: dict[str, float | None] = {}
        aliases = {
            "first_serve_win": ("firstServeWon", "first_serve_won", "win_1st_serve", "firstServeWinPct"),
            "second_serve_win": ("secondServeWon", "second_serve_won", "win_2nd_serve", "secondServeWinPct"),
            "ace_rate": ("aceRate", "ace_rate", "acesPct"),
            "return_points_won": ("returnPointsWon", "return_points_won", "returnWinPct"),
            "break_points_won": ("breakPointsWon", "break_points_won", "breakPointConversion"),
        }
        for prefix, provider_side in (("p1", "player1"), ("p2", "player2")):
            for canonical, names in aliases.items():
                result[f"{prefix}_{canonical}"] = side_value(provider_side, names)
        return result

    @classmethod
    def normalize_match(cls, raw: dict[str, Any], tour: str, historical: bool) -> MatchRecord:
        p1_id, p1_name, p1_rank = cls._player(raw, 1)
        p2_id, p2_name, p2_rank = cls._player(raw, 2)
        tournament_obj = first_present(raw, "tournament", "tour", "event")
        if not isinstance(tournament_obj, dict):
            tournament_obj = {}
        court_obj = first_present(tournament_obj, "court", "surface")
        rank_obj = first_present(tournament_obj, "rank", "level", "category")

        surface_value: Any = first_present(raw, "surface", "court", "courtName")
        if isinstance(court_obj, dict):
            surface_value = first_present(court_obj, "name", "court_name", "type") or surface_value
        elif isinstance(court_obj, str):
            surface_value = court_obj

        level_value: Any = first_present(raw, "tournamentLevel", "level", "rankName")
        if isinstance(rank_obj, dict):
            level_value = first_present(rank_obj, "name", "rank_name", "title") or level_value
        elif isinstance(rank_obj, str):
            level_value = rank_obj

        tournament_name = first_present(raw, "tournamentName", "eventName")
        tournament_id = first_present(raw, "tournamentId", "tourId", "seasonId", "seasonid")
        if tournament_obj:
            tournament_name = tournament_name or first_present(tournament_obj, "name", "tournamentName", "title")
            tournament_id = tournament_id or first_present(tournament_obj, "id", "seasonid", "seasonId", "tournamentId")

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
        result_text = first_present(raw, "result", "score", "finalScore")
        status = str(
            first_present(raw, "status", "state")
            or ("completed" if result_text not in (None, "") else "upcoming")
        )

        winner_id: str | None = None
        explicit_winner = first_present(raw, "winnerId", "winner_id")
        completed_status = status.lower() in {
            "completed", "complete", "ended", "finished", "final", "retired", "walkover"
        }
        if explicit_winner is not None:
            winner_id = str(explicit_winner)
        elif result_text not in (None, "") or completed_status:
            # Provider docs guarantee winner-first ordering in the historical Game archive.
            winner_id = p1_id

        round_obj = first_present(raw, "round", "roundInfo")
        round_name = first_present(raw, "roundName", "round_name")
        round_id = first_present(raw, "roundId", "round_id")
        if isinstance(round_obj, dict):
            round_id = round_id or first_present(round_obj, "id", "roundId", "key")
            round_name = round_name or first_present(round_obj, "name", "roundName", "title")
        elif isinstance(round_obj, str):
            round_name = round_name or round_obj
        round_token = round_id or round_name or ""

        scheduled_dt = parse_datetime(scheduled)
        # Canonical ID is deliberately independent of provider table IDs and player order.
        # Upcoming fixtures and the historical winner-first archive can therefore settle
        # against the same prediction even when provider IDs/order differ.
        player_pair = sorted((p1_id, p2_id))
        match_id = deterministic_id(
            [
                tour,
                scheduled_dt.date().isoformat(),
                tournament_id,
                player_pair[0],
                player_pair[1],
                round_token,
            ]
        )

        best_of = safe_int(first_present(raw, "bestOf", "best_of", "setsToPlay"))
        indoor_raw = first_present(raw, "indoor", "isIndoor")
        indoor = None if indoor_raw is None else bool(indoor_raw)
        surface = normalize_surface(surface_value)
        if surface == "indoor_hard":
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
            tournament=str(tournament_name or ""),
            tournament_id=str(tournament_id or ""),
            tournament_level=str(level_value or ""),
            round_name=str(round_name or ""),
            player1_rank=p1_rank,
            player2_rank=p2_rank,
            winner_id=winner_id,
            status=status,
            best_of=best_of,
            indoor=indoor,
            stats=cls._stats(raw),
            provider_payload=raw,
        )
