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
    """TennisApi PRO adapter for ``tennisapi1.p.rapidapi.com``.

    Daily coverage follows the provider-confirmed flow:

      1. GET /api/tennis/calendar/{day}/{month}/{year}/categories
      2. GET /api/tennis/category/{categoryId}/events/{day}/{month}/{year}

    The retired flat ``/api/tennis/events/...`` endpoint and legacy ``/tennis/v2``
    fixtures are intentionally not used.
    """

    DEFAULT_HOST = "tennisapi1.p.rapidapi.com"
    DEFAULT_BASE_URL = "https://tennisapi1.p.rapidapi.com"
    OBSOLETE_HOSTS = {"tennis-api-atp-wta-itf.p.rapidapi.com"}

    CATEGORY_ATP = 3
    CATEGORY_WTA = 6
    CATEGORY_CHALLENGER = 72
    CATEGORY_ITF_WOMEN = 213
    CATEGORY_ITF_MEN = 785
    CATEGORY_WTA125 = 871
    CATEGORY_GRAND_SLAM = -100

    # TBT production target remains ATP/WTA. Challenger/ITF categories are not
    # silently relabelled as ATP/WTA main-tour events.
    MAIN_TOUR_CATEGORY_IDS = {
        "atp": {CATEGORY_ATP, CATEGORY_GRAND_SLAM},
        "wta": {CATEGORY_WTA, CATEGORY_WTA125, CATEGORY_GRAND_SLAM},
    }

    FINISHED_STATUS_TYPES = {
        "finished", "complete", "completed", "ended", "final", "retired",
        "walkover", "walk over",
    }
    NON_PREDICTABLE_STATUS_TYPES = {
        "canceled", "cancelled", "postponed", "suspended", "interrupted",
        "abandoned", "retired", "walkover", "walk over", "finished",
        "complete", "completed", "ended", "final",
    }

    def __init__(self, cfg: Settings = settings) -> None:
        if not cfg.rapidapi_key:
            raise ConfigurationError("RAPIDAPI_KEY is required")

        self.cfg = cfg
        configured_host = str(getattr(cfg, "rapidapi_host", "") or "").strip()
        configured_base = str(getattr(cfg, "rapidapi_base_url", "") or "").strip()

        if not configured_host or configured_host in self.OBSOLETE_HOSTS:
            configured_host = self.DEFAULT_HOST
        if not configured_base or any(old in configured_base for old in self.OBSOLETE_HOSTS):
            configured_base = self.DEFAULT_BASE_URL

        self.host = configured_host
        self.base_url = configured_base.rstrip("/")
        self.client = httpx.Client(timeout=cfg.request_timeout_seconds)
        self._last_request_at = 0.0
        self._calendar_cache: dict[str, list[dict[str, Any]]] = {}
        self._events_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.request_count = 0
        self.rate_limit_remaining: int | None = None
        self.rate_limit_limit: int | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-RapidAPI-Key": self.cfg.rapidapi_key,
            "X-RapidAPI-Host": self.host,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "TBT/2.3",
        }

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        minimum_interval = 0.25
        if elapsed < minimum_interval:
            time.sleep(minimum_interval - elapsed)

    @staticmethod
    def _header_int(response: httpx.Response, name: str) -> int | None:
        value = response.headers.get(name)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(5):
            self._throttle()
            try:
                response = self.client.get(url, headers=self.headers, params=params or {})
                self._last_request_at = time.monotonic()
                self.request_count += 1
                self.rate_limit_remaining = self._header_int(
                    response, "x-ratelimit-requests-remaining"
                )
                self.rate_limit_limit = self._header_int(
                    response, "x-ratelimit-requests-limit"
                )

                if response.status_code == 204:
                    return {}
                if response.status_code in {401, 403}:
                    raise ProviderError(
                        "TennisApi authentication/subscription error "
                        f"HTTP {response.status_code} for {url}. "
                        f"Response={response.text[:500]}"
                    )
                if response.status_code == 404:
                    raise ProviderError(
                        f"TennisApi endpoint not found: {url}. Response={response.text[:500]}"
                    )
                if response.status_code == 429:
                    retry_header = response.headers.get("Retry-After")
                    try:
                        delay = float(retry_header) if retry_header else 2 + attempt * 2
                    except ValueError:
                        delay = 2 + attempt * 2
                    logger.warning("RapidAPI rate limit hit; sleeping %.1fs", delay)
                    time.sleep(min(max(delay, 1.0), 60.0))
                    continue
                if response.status_code >= 500:
                    time.sleep(min(2**attempt, 20))
                    continue

                response.raise_for_status()
                if not response.content:
                    return {}
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
            "events", "categories", "rankings", "data", "result", "results",
            "matches", "fixtures", "tournaments",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _unwrap_category(category: dict[str, Any]) -> dict[str, Any]:
        nested = category.get("category")
        return nested if isinstance(nested, dict) else category

    @classmethod
    def _category_id(cls, category: dict[str, Any]) -> int | None:
        category = cls._unwrap_category(category)
        return safe_int(first_present(category, "id", "categoryId", "category_id"))

    def _calendar_categories(self, day: date) -> list[dict[str, Any]]:
        key = day.isoformat()
        if key not in self._calendar_cache:
            payload = self._get(
                f"/api/tennis/calendar/{day.day}/{day.month}/{day.year}/categories"
            )
            self._calendar_cache[key] = self._data(payload)
        return self._calendar_cache[key]

    def _events_for_category_day(
        self, category_id: int | str, day: date
    ) -> list[dict[str, Any]]:
        key = (day.isoformat(), str(category_id))
        if key not in self._events_cache:
            payload = self._get(
                f"/api/tennis/category/{category_id}/events/"
                f"{day.day}/{day.month}/{day.year}"
            )
            self._events_cache[key] = self._data(payload)
        return self._events_cache[key]

    @staticmethod
    def _event_tour(raw: dict[str, Any]) -> str | None:
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

        text = " ".join(
            str(x or "")
            for x in (
                first_present(category, "name", "slug", "title"),
                first_present(tournament, "name", "slug", "title"),
                first_present(unique, "name", "slug", "title"),
            )
        ).lower()
        if "wta" in text or "women" in text:
            return "wta"
        if "atp" in text or "men" in text:
            return "atp"

        genders: list[str] = []
        for side in ("homeTeam", "awayTeam"):
            obj = raw.get(side)
            if isinstance(obj, dict):
                gender = str(first_present(obj, "gender", "genderCode") or "").lower()
                if gender:
                    genders.append(gender)
        if genders and all(g in {"m", "male", "men", "man"} for g in genders):
            return "atp"
        if genders and all(g in {"f", "female", "women", "woman"} for g in genders):
            return "wta"
        return None

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
            if isinstance(team.get("subTeams"), list) and len(team["subTeams"]) > 1:
                return True
        return False

    def _active_category_ids(self, day: date, tour: str) -> list[int]:
        allowed = self.MAIN_TOUR_CATEGORY_IDS[tour]
        active: list[int] = []
        for category in self._calendar_categories(day):
            category_id = self._category_id(category)
            if category_id is not None and category_id in allowed:
                active.append(category_id)
        return sorted(set(active))

    @classmethod
    def _raw_event_day(cls, raw: dict[str, Any]) -> date | None:
        value = first_present(raw, "startTimestamp", "startTime", "scheduledAt", "date")
        if value in (None, ""):
            return None
        try:
            return cls._provider_datetime(value).date()
        except Exception:
            return None

    @classmethod
    def _raw_status(cls, raw: dict[str, Any]) -> str:
        return cls._status_type(raw)

    @classmethod
    def _raw_is_predictable(cls, raw: dict[str, Any]) -> bool:
        status = cls._raw_status(raw)
        return status not in cls.NON_PREDICTABLE_STATUS_TYPES

    def _matches_for_day(
        self, tour: str, day: date, historical: bool
    ) -> list[MatchRecord]:
        tour = tour.lower()
        if tour not in {"atp", "wta"}:
            raise ValueError("tour must be atp or wta")

        matches: dict[str, MatchRecord] = {}
        seen_provider_ids: set[str] = set()

        for category_id in self._active_category_ids(day, tour):
            for raw in self._events_for_category_day(category_id, day):
                provider_id = str(raw.get("id") or "").strip()
                if provider_id and provider_id in seen_provider_ids:
                    continue

                # The date feed can include edge-of-day events. Keep only events whose
                # actual UTC start date matches the requested UTC date.
                raw_day = self._raw_event_day(raw)
                if raw_day is not None and raw_day != day:
                    continue

                if self._looks_like_doubles(raw):
                    continue

                if category_id == self.CATEGORY_GRAND_SLAM:
                    detected_tour = self._event_tour(raw)
                    if detected_tour != tour:
                        continue

                if not historical and not self._raw_is_predictable(raw):
                    continue

                raw_for_normalize = dict(raw)
                raw_for_normalize["_tbt_source_category_id"] = category_id

                try:
                    match = self.normalize_match(
                        raw_for_normalize, tour=tour, historical=historical
                    )
                except Exception as exc:
                    logger.warning(
                        "Skipping malformed TennisApi event id=%s: %s", raw.get("id"), exc
                    )
                    continue

                if provider_id:
                    seen_provider_ids.add(provider_id)
                matches[match.match_id] = match

        return list(matches.values())

    def upcoming(
        self, tour: str, start: date, end: date | None = None
    ) -> list[MatchRecord]:
        tour = tour.lower()
        if tour not in {"atp", "wta"}:
            raise ValueError("tour must be atp or wta")
        end = end or start
        if end < start:
            raise ValueError("end must be >= start")

        now = datetime.now(timezone.utc)
        matches: dict[str, MatchRecord] = {}
        current = start
        while current <= end:
            for match in self._matches_for_day(tour, current, historical=False):
                if match.scheduled_at > now and not match.is_completed:
                    matches[match.match_id] = match
            current += timedelta(days=1)
        return sorted(matches.values(), key=lambda match: match.scheduled_at)

    def historical_period(self, tour: str, start: date, end: date) -> list[MatchRecord]:
        """Fetch real completed singles matches for a bounded period."""
        tour = tour.lower()
        if tour not in {"atp", "wta"}:
            raise ValueError("tour must be atp or wta")
        if end < start:
            return []

        yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
        end = min(end, yesterday)
        if end < start:
            return []

        matches: dict[str, MatchRecord] = {}
        current = start
        last_month: tuple[int, int] | None = None

        while current <= end:
            month_key = (current.year, current.month)
            if month_key != last_month:
                logger.info(
                    "TennisApi bootstrap %s %04d-%02d (requests=%s remaining=%s)",
                    tour.upper(), current.year, current.month,
                    self.request_count, self.rate_limit_remaining,
                )
                last_month = month_key

            for match in self._matches_for_day(tour, current, historical=True):
                if match.is_completed and match.winner_id:
                    matches[match.match_id] = match
            current += timedelta(days=1)

        return sorted(matches.values(), key=lambda match: match.scheduled_at)

    def historical_year(self, tour: str, year: int) -> list[MatchRecord]:
        return self.historical_period(tour, date(year, 1, 1), date(year, 12, 31))

    def rankings(self, tour: str) -> list[dict[str, Any]]:
        """Current ranking snapshot only; never use retrospectively in backtests."""
        tour = tour.lower()
        if tour not in {"atp", "wta"}:
            raise ValueError("tour must be atp or wta")
        # RapidAPI UI currently exposes getATP/WTA rankings without date parameters.
        endpoint = "atp" if tour == "atp" else "wta"
        payload = self._get(f"/api/tennis/rankings/{endpoint}/")
        return self._data(payload)

    def player_rankings(self, player_id: str | int) -> Any:
        """Current player ranking record, including previous/best ranking when available."""
        return self._get(f"/api/tennis/player/{player_id}/rankings")

    def previous_player_matches(self, player_id: str | int, page: int = 0) -> Any:
        """Provider player-history endpoint; useful for validation/enrichment."""
        return self._get(f"/api/tennis/player/{player_id}/events/last/{page}")

    def event_details(self, event_id: str | int) -> Any:
        return self._get(f"/api/tennis/event/{event_id}")

    def event_statistics(self, event_id: str | int) -> Any:
        return self._get(f"/api/tennis/event/{event_id}/statistics")

    def event_odds(self, event_id: str | int, provider_id: int = 1) -> Any:
        return self._get(f"/api/tennis/event/{event_id}/odds/{provider_id}/all")

    @staticmethod
    def provider_event_id(match: MatchRecord) -> str | None:
        raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
        value = raw.get("id")
        return str(value) if value not in (None, "") else None

    @staticmethod
    def _player(raw: dict[str, Any], side: str) -> tuple[str, str, int | None]:
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
            status_type = str(first_present(status, "type", "name") or "").strip().lower()
            description = str(first_present(status, "description") or "").strip().lower()
            for special in (
                "retired", "walkover", "walk over", "cancelled", "canceled",
                "postponed", "suspended", "interrupted", "abandoned",
            ):
                if special in description:
                    if "walk" in special:
                        return "walkover"
                    return special.replace("cancelled", "canceled")
            return status_type or description or "unknown"
        return str(status or "unknown").strip().lower()

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
        cls, raw: dict[str, Any], p1_id: str, p2_id: str, status: str
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
                "firstServeWon", "firstServePointsWon", "first_serve_won",
                "firstServeWinPct",
            ),
            "second_serve_win": (
                "secondServeWon", "secondServePointsWon", "second_serve_won",
                "secondServeWinPct",
            ),
            "ace_rate": ("aceRate", "ace_rate", "acesPct", "aces"),
            "return_points_won": (
                "returnPointsWon", "return_points_won", "returnWinPct",
            ),
            "break_points_won": (
                "breakPointsWon", "break_points_won", "breakPointConversion",
            ),
        }

        def side_value(
            side_aliases: tuple[str, ...], names: tuple[str, ...]
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
        cls, raw: dict[str, Any], tour: str, historical: bool
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

        # uniqueTournament is the stable competition identity; tournament.name may
        # be a transient round/edition label. Prefer unique name when available.
        tournament_name = first_present(unique, "name", "title") or first_present(
            tournament, "name", "title"
        )
        tournament_id = first_present(unique, "id", "uniqueTournamentId") or first_present(
            tournament, "id", "tournamentId"
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
            raw, "startTimestamp", "startTime", "scheduledAt", "scheduled_at", "date"
        )
        if scheduled in (None, ""):
            raise ValueError("TennisApi event has no startTimestamp")

        scheduled_dt = cls._provider_datetime(scheduled)
        status = cls._status_type(raw)
        winner_id = cls._winner_id(raw, p1_id, p2_id, status)

        # Current ranking is not point-in-time history. Never leak today's rank
        # backwards into historical training rows.
        if historical:
            p1_rank = None
            p2_rank = None

        best_of = safe_int(first_present(raw, "bestOf", "best_of", "setsToPlay"))
        if best_of is None:
            best_of = safe_int(first_present(tournament, "bestOf", "setsToPlay"))

        player_pair = sorted((p1_id, p2_id))
        match_id = deterministic_id(
            [
                tour.lower(), scheduled_dt.date().isoformat(), tournament_id or "",
                player_pair[0], player_pair[1], round_name,
            ]
        )

        # Preserve stable provider identity and structured location hints for later
        # weather/travel enrichment without changing the DB schema.
        payload = dict(raw)
        payload["_tbt_provider_event_id"] = raw.get("id")
        payload["_tbt_unique_tournament_id"] = first_present(
            unique, "id", "uniqueTournamentId"
        )
        payload["_tbt_tournament_name"] = str(tournament_name or "")

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
            provider_payload=payload,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "RapidTennisClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
