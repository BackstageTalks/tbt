from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import Settings, settings
from ..errors import ConfigurationError, ProviderError
from ..schemas import MatchRecord
from ..utils import (
    deterministic_id,
    first_present,
    normalize_surface,
    parse_datetime,
    safe_float,
    safe_int,
)

logger = logging.getLogger(__name__)


class RapidTennisClient:
    """RapidAPI adapter for Fidel Lacasse's TennisApi (tennisapi1).

    RapidAPI host:
        tennisapi1.p.rapidapi.com

    The provider uses a SofaScore-like event schema (``homeTeam``, ``awayTeam``,
    ``winnerCode``, ``status`` and ``startTimestamp``).  The TBT domain model
    remains provider-independent; all provider-specific details live here.

    The daily bootstrap follows the provider's recommended tennis flow:

        /api/tennis/calendar/{day}/{month}/{year}/categories
            -> /api/tennis/category/{category_id}/events/{day}/{month}/{year}

    Only ATP/WTA singles events are retained.
    """

    DEFAULT_HOST = "tennisapi1.p.rapidapi.com"
    DEFAULT_BASE_URL = "https://tennisapi1.p.rapidapi.com"
    OBSOLETE_HOSTS = {"tennis-api-atp-wta-itf.p.rapidapi.com"}

    FINISHED_STATUS_TYPES = {
        "finished",
        "complete",
        "completed",
        "ended",
        "final",
        "retired",
        "walkover",
    }

    def __init__(self, cfg: Settings = settings) -> None:
        if not cfg.rapidapi_key:
            raise ConfigurationError("RAPIDAPI_KEY is required")

        self.cfg = cfg

        configured_host = str(getattr(cfg, "rapidapi_host", "") or "").strip()
        configured_base = str(getattr(cfg, "rapidapi_base_url", "") or "").strip()

        if not configured_host or configured_host in self.OBSOLETE_HOSTS:
            configured_host = self.DEFAULT_HOST

        if (
            not configured_base
            or any(old in configured_base for old in self.OBSOLETE_HOSTS)
        ):
            configured_base = self.DEFAULT_BASE_URL

        self.host = configured_host
        self.base_url = configured_base.rstrip("/")
        self.client = httpx.Client(timeout=cfg.request_timeout_seconds)
        self._last_request_at = 0.0

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-RapidAPI-Key": self.cfg.rapidapi_key,
            "X-RapidAPI-Host": self.host,
            "Accept": "application/json",
            "User-Agent": "TBT-v200/2.1",
        }

    def _throttle(self) -> None:
        # Keep some margin for RapidAPI throttling while still allowing a full
        # historical year to complete comfortably inside the workflow timeout.
        elapsed = time.monotonic() - self._last_request_at
        minimum_interval = 0.25
        if elapsed < minimum_interval:
            time.sleep(minimum_interval - elapsed)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not path.startswith("/"):
            path = "/" + path

        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(5):
            self._throttle()
            try:
                response = self.client.get(
                    url,
                    headers=self.headers,
                    params=params or {},
                )
                self._last_request_at = time.monotonic()

                if response.status_code in {401, 403}:
                    raise ProviderError(
                        "TennisApi1 authentication/subscription error "
                        f"HTTP {response.status_code} for {url}. "
                        f"Response={response.text[:500]}"
                    )

                if response.status_code == 404:
                    raise ProviderError(
                        f"TennisApi1 endpoint not found: {url}. "
                        f"Response={response.text[:500]}"
                    )

                if response.status_code == 429:
                    retry_header = response.headers.get("Retry-After")
                    try:
                        delay = float(retry_header) if retry_header else 2 + attempt * 2
                    except ValueError:
                        delay = 2 + attempt * 2
                    time.sleep(min(max(delay, 1.0), 60.0))
                    continue

                if response.status_code >= 500:
                    time.sleep(min(2**attempt, 20))
                    continue

                response.raise_for_status()
                return response.json()

            except ProviderError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 4:
                    time.sleep(min(2**attempt, 10))

        raise ProviderError(f"RapidAPI request failed: {url}: {last_error}")

    @staticmethod
    def _data(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]

        if not isinstance(payload, dict):
            return []

        for key in (
            "events",
            "categories",
            "rankings",
            "data",
            "result",
            "results",
            "matches",
            "fixtures",
            "tournaments",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

        return []

    @staticmethod
    def _category_id(category: dict[str, Any]) -> str | None:
        value = first_present(category, "id", "categoryId", "category_id")
        return None if value in (None, "") else str(value)

    @staticmethod
    def _category_name(category: dict[str, Any]) -> str:
        return str(first_present(category, "name", "slug", "title") or "").strip()

    @classmethod
    def _category_matches_tour(cls, category: dict[str, Any], tour: str) -> bool:
        text = cls._category_name(category).lower()
        if tour == "atp":
            return text == "atp" or text.startswith("atp ") or text.startswith("atp-")
        if tour == "wta":
            return text == "wta" or text.startswith("wta ") or text.startswith("wta-")
        return False

    def _calendar_categories(self, day: date) -> list[dict[str, Any]]:
        payload = self._get(
            f"/api/tennis/calendar/{day.day}/{day.month}/{day.year}/categories"
        )
        return self._data(payload)

    def _events_for_category_day(
        self,
        category_id: str,
        day: date,
    ) -> list[dict[str, Any]]:
        payload = self._get(
            f"/api/tennis/category/{category_id}/events/"
            f"{day.day}/{day.month}/{day.year}"
        )
        return self._data(payload)

    @staticmethod
    def _looks_like_doubles(raw: dict[str, Any]) -> bool:
        tournament = raw.get("tournament")
        if not isinstance(tournament, dict):
            tournament = {}

        unique = tournament.get("uniqueTournament")
        if not isinstance(unique, dict):
            unique = {}

        for value in (
            first_present(tournament, "name", "slug"),
            first_present(unique, "name", "slug"),
        ):
            if "double" in str(value or "").lower():
                return True

        for side in ("homeTeam", "awayTeam"):
            team = raw.get(side)
            if not isinstance(team, dict):
                continue
            name = str(first_present(team, "name", "shortName", "fullName") or "")
            if " / " in name:
                return True

        return False

    def _matches_for_day(
        self,
        tour: str,
        day: date,
        historical: bool,
    ) -> list[MatchRecord]:
        matches: dict[str, MatchRecord] = {}

        categories = [
            category
            for category in self._calendar_categories(day)
            if self._category_matches_tour(category, tour)
        ]

        for category in categories:
            category_id = self._category_id(category)
            if not category_id:
                continue

            for raw in self._events_for_category_day(category_id, day):
                if self._looks_like_doubles(raw):
                    continue

                try:
                    match = self.normalize_match(raw, tour=tour, historical=historical)
                except Exception as exc:
                    logger.warning(
                        "Skipping malformed TennisApi1 event id=%s: %s",
                        raw.get("id"),
                        exc,
                    )
                    continue

                matches[match.match_id] = match

        return list(matches.values())

    def upcoming(
        self,
        tour: str,
        start: date,
        end: date | None = None,
    ) -> list[MatchRecord]:
        tour = tour.lower()
        if tour not in {"atp", "wta"}:
            raise ValueError("tour must be atp or wta")

        end = end or start
        if end < start:
            raise ValueError("end must be >= start")

        matches: dict[str, MatchRecord] = {}
        current = start
        while current <= end:
            for match in self._matches_for_day(tour, current, historical=False):
                if not match.is_completed:
                    matches[match.match_id] = match
            current += timedelta(days=1)

        return sorted(matches.values(), key=lambda match: match.scheduled_at)

    def historical_year(self, tour: str, year: int) -> list[MatchRecord]:
        """Fetch a complete ATP/WTA singles year using TennisApi1 daily schedules."""

        tour = tour.lower()
        if tour not in {"atp", "wta"}:
            raise ValueError("tour must be atp or wta")

        matches: dict[str, MatchRecord] = {}
        current = date(year, 1, 1)
        finish = date(year, 12, 31)
        last_month: int | None = None

        while current <= finish:
            if current.month != last_month:
                logger.info(
                    "TennisApi1 bootstrap %s %s-%02d",
                    tour.upper(),
                    current.year,
                    current.month,
                )
                last_month = current.month

            for match in self._matches_for_day(tour, current, historical=True):
                # Schedule endpoints can overlap the UTC day boundary.
                if match.scheduled_at.year != year:
                    continue
                if match.is_completed and match.winner_id:
                    matches[match.match_id] = match

            current += timedelta(days=1)

        result = sorted(matches.values(), key=lambda match: match.scheduled_at)
        logger.info(
            "TennisApi1 %s %s: %s completed singles matches",
            tour.upper(),
            year,
            len(result),
        )
        return result

    def rankings(self, tour: str) -> list[dict[str, Any]]:
        tour = tour.lower()
        if tour not in {"atp", "wta"}:
            raise ValueError("tour must be atp or wta")
        return self._data(self._get(f"/api/tennis/rankings/{tour}/"))

    @staticmethod
    def _player(
        raw: dict[str, Any],
        side: str,
    ) -> tuple[str, str, int | None]:
        obj = raw.get(side)
        if not isinstance(obj, dict):
            obj = {}

        player_id = first_present(obj, "id", "playerId", "player_id", "teamId")
        name = first_present(obj, "name", "fullName", "shortName", "playerName")
        rank = first_present(obj, "ranking", "rank", "position")

        number = 1 if side == "homeTeam" else 2
        name = str(name or f"Player {number}").strip()
        player_id = str(player_id or f"name:{name.lower()}").strip()
        return player_id, name, safe_int(rank)

    @staticmethod
    def _provider_datetime(value: Any) -> datetime:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        if isinstance(value, str) and value.strip().isdigit():
            return datetime.fromtimestamp(float(value.strip()), tz=timezone.utc)
        return parse_datetime(value)

    @staticmethod
    def _status_type(raw: dict[str, Any]) -> str:
        status = raw.get("status")
        if isinstance(status, dict):
            value = first_present(status, "type", "description", "name")
        else:
            value = status
        return str(value or "unknown").strip().lower()

    @staticmethod
    def _score_number(raw: dict[str, Any], side: str) -> int | None:
        score = raw.get(side)
        if not isinstance(score, dict):
            return safe_int(score)

        for key in ("norm", "current", "display"):
            value = safe_int(score.get(key))
            if value is not None:
                return value
        return None

    @classmethod
    def _winner_id(
        cls,
        raw: dict[str, Any],
        p1_id: str,
        p2_id: str,
        status: str,
    ) -> str | None:
        winner_code = safe_int(first_present(raw, "winnerCode", "winner_code"))
        if winner_code == 1:
            return p1_id
        if winner_code == 2:
            return p2_id

        if status not in cls.FINISHED_STATUS_TYPES:
            return None

        home_score = cls._score_number(raw, "homeScore")
        away_score = cls._score_number(raw, "awayScore")
        if home_score is not None and away_score is not None and home_score != away_score:
            return p1_id if home_score > away_score else p2_id
        return None

    @staticmethod
    def _stats(raw: dict[str, Any]) -> dict[str, float | None]:
        stat = first_present(raw, "stat", "stats", "statistics")
        if not isinstance(stat, dict):
            return {}

        aliases = {
            "first_serve_win": (
                "firstServeWon",
                "firstServePointsWon",
                "first_serve_won",
                "firstServeWinPct",
            ),
            "second_serve_win": (
                "secondServeWon",
                "secondServePointsWon",
                "second_serve_won",
                "secondServeWinPct",
            ),
            "ace_rate": ("aceRate", "ace_rate", "acesPct", "aces"),
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

        def side_value(
            side_aliases: tuple[str, ...],
            names: tuple[str, ...],
        ) -> float | None:
            for side in side_aliases:
                side_obj = stat.get(side)
                if isinstance(side_obj, dict):
                    for name in names:
                        if name in side_obj:
                            return safe_float(side_obj[name])
            return None

        result: dict[str, float | None] = {}
        for prefix, sides in {
            "p1": ("home", "homeTeam", "player1"),
            "p2": ("away", "awayTeam", "player2"),
        }.items():
            for canonical, names in aliases.items():
                result[f"{prefix}_{canonical}"] = side_value(sides, names)
        return result

    @classmethod
    def normalize_match(
        cls,
        raw: dict[str, Any],
        tour: str,
        historical: bool,
    ) -> MatchRecord:
        p1_id, p1_name, p1_rank = cls._player(raw, "homeTeam")
        p2_id, p2_name, p2_rank = cls._player(raw, "awayTeam")

        tournament = raw.get("tournament")
        if not isinstance(tournament, dict):
            tournament = {}

        unique = tournament.get("uniqueTournament")
        if not isinstance(unique, dict):
            unique = {}

        category = tournament.get("category")
        if not isinstance(category, dict):
            category = unique.get("category")
        if not isinstance(category, dict):
            category = {}

        tournament_name = first_present(tournament, "name", "title") or first_present(
            unique, "name", "title"
        )
        tournament_id = first_present(tournament, "id", "tournamentId") or first_present(
            unique, "id", "uniqueTournamentId"
        )
        level_value = first_present(category, "name", "slug")

        surface_value: Any = first_present(raw, "groundType", "surface", "court")
        if surface_value in (None, ""):
            surface_value = first_present(tournament, "groundType", "surface", "court")
        if surface_value in (None, ""):
            surface_value = first_present(unique, "groundType", "surface", "court")

        surface_text = str(surface_value or "").strip()
        surface = normalize_surface(surface_text)

        indoor: bool | None = None
        lower_surface = surface_text.lower()
        if "indoor" in lower_surface:
            indoor = True
        elif "outdoor" in lower_surface:
            indoor = False
        elif surface == "indoor_hard":
            indoor = True

        round_info = raw.get("roundInfo")
        if not isinstance(round_info, dict):
            round_info = {}
        round_name = first_present(round_info, "name", "roundName", "round") or first_present(
            raw, "roundName", "round"
        )
        round_name = str(round_name or "")

        scheduled = first_present(
            raw,
            "startTimestamp",
            "startTime",
            "scheduledAt",
            "scheduled_at",
            "date",
        )
        if scheduled in (None, ""):
            raise ValueError("TennisApi1 event has no startTimestamp")

        scheduled_dt = cls._provider_datetime(scheduled)
        status = cls._status_type(raw)
        winner_id = cls._winner_id(raw, p1_id, p2_id, status)

        # Do not trust event.player.ranking as an historical point-in-time value.
        # Current rankings in old rows would create severe future-data leakage.
        if historical:
            p1_rank = None
            p2_rank = None

        best_of = safe_int(first_present(raw, "bestOf", "best_of", "setsToPlay"))
        if best_of is None:
            best_of = safe_int(first_present(tournament, "bestOf", "setsToPlay"))

        player_pair = sorted((p1_id, p2_id))
        match_id = deterministic_id(
            [
                tour.lower(),
                scheduled_dt.date().isoformat(),
                tournament_id or "",
                player_pair[0],
                player_pair[1],
                round_name,
            ]
        )

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
            round_name=round_name,
            player1_rank=p1_rank,
            player2_rank=p2_rank,
            winner_id=winner_id,
            status=status,
            best_of=best_of,
            indoor=indoor,
            stats=cls._stats(raw),
            provider_payload=raw,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "RapidTennisClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
