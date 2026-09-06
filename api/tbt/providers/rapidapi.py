from __future__ import annotations

import logging
import math
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable

import httpx

from ..config import Settings, settings
from ..data.history_snapshot import merge_matches
from ..errors import ConfigurationError, ProviderError
from .budget import RequestBudgetExceeded
from ..schemas import MatchRecord
from ..utils import (
    deterministic_id,
    dig,
    first_present,
    normalize_surface,
    normalize_rate,
    parse_datetime,
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

    def __init__(self, cfg: Settings = settings, *, request_budget=None) -> None:
        if not cfg.rapidapi_key:
            raise ConfigurationError(
                "RAPIDAPI_KEY is required"
            )

        self.cfg = cfg
        self.request_budget = request_budget
        self.client = httpx.Client(
            timeout=cfg.request_timeout_seconds
        )
        self._last_request_at = 0.0
        self.request_count = 0
        self.request_limit = 15000
        self.rate_limit_remaining = None
        self._category_cache: dict[str, list[dict[str, Any]]] = {}
        self._event_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}

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

    @staticmethod
    def _retry_after_seconds(value: Any) -> float | None:
        """Parse Retry-After as seconds or an HTTP-date."""
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        try:
            seconds = float(text)
        except ValueError:
            seconds = None

        if seconds is not None:
            if not math.isfinite(seconds) or seconds < 0:
                return None
            return seconds

        try:
            retry_at = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None

        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)

        delay = (
            retry_at.astimezone(timezone.utc)
            - datetime.now(timezone.utc)
        ).total_seconds()

        return max(delay, 0.0)

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        enrichment: bool = False,
    ) -> Any:
        url = (
            f"{self.cfg.rapidapi_base_url}"
            f"{path}"
        )

        last_error: Exception | None = None

        for attempt in range(5):
            self._throttle()

            # Reserve outside the retry block: budget/storage failures fail closed.
            if self.request_limit is not None and self.request_count >= self.request_limit:
                raise RequestBudgetExceeded("Per-run request limit exhausted")
            if self.rate_limit_remaining == 0:
                raise RequestBudgetExceeded("Provider reports no remaining requests")
            if self.request_budget is not None:
                self.request_budget(self.client, self.cfg, enrichment=enrichment)

            try:
                self._last_request_at = time.monotonic()
                self.request_count += 1
                response = self.client.get(
                    url,
                    headers=self.headers,
                    params=params or {},
                )

                remaining = response.headers.get("x-ratelimit-requests-remaining")
                if remaining is not None:
                    self.rate_limit_remaining = safe_int(remaining)

                if response.status_code == 429:
                    delay = self._retry_after_seconds(
                        response.headers.get("Retry-After")
                    )
                    delay = delay if delay is not None else 2 + attempt * 2

                    # Honor the entire server delay, including long HTTP-date
                    # delays. Chunking keeps waits interruptible without retrying.
                    remaining_delay = max(delay, 1.0)
                    while remaining_delay > 0:
                        pause = min(remaining_delay, 60.0)
                        time.sleep(pause)
                        remaining_delay -= pause
                    continue

                if response.status_code >= 500:
                    time.sleep(
                        min(
                            2**attempt,
                            15,
                        )
                    )
                    continue

                if 400 <= response.status_code < 500:
                    raise ProviderError(
                        f"RapidAPI HTTP {response.status_code} for {path}: "
                        f"{response.text[:300]}"
                    )

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
            "categories",
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

    @classmethod
    def _named_list(
        cls,
        payload: Any,
        key: str,
    ) -> list[dict[str, Any]]:
        """Find a list under *key* even when TennisApi wraps it in data/result."""
        if isinstance(payload, list):
            return [
                row
                for row in payload
                if isinstance(row, dict)
            ]

        if not isinstance(payload, dict):
            return []

        value = payload.get(key)
        if isinstance(value, list):
            return [
                row
                for row in value
                if isinstance(row, dict)
            ]

        for nested in payload.values():
            if isinstance(nested, dict):
                rows = cls._named_list(
                    nested,
                    key,
                )
                if rows:
                    return rows

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

    CATEGORY_ATP = 3
    CATEGORY_WTA = 6
    CATEGORY_CHALLENGER = 72
    CATEGORY_ITF_WOMEN = 213
    CATEGORY_ITF_MEN = 785
    CATEGORY_WTA125 = 871
    CATEGORY_GRAND_SLAM = -100

    _ATP_CATEGORY_IDS = {
        CATEGORY_ATP,
        CATEGORY_CHALLENGER,
        CATEGORY_ITF_MEN,
    }
    _WTA_CATEGORY_IDS = {
        CATEGORY_WTA,
        CATEGORY_ITF_WOMEN,
        CATEGORY_WTA125,
    }

    @staticmethod
    def _day_token(day: date) -> str:
        # TennisApi explicitly documents non-zero-padded dates.
        return f"{day.day}/{day.month}/{day.year}"

    @staticmethod
    def _category_id(category: dict[str, Any]) -> int | None:
        nested = (
            category.get("category")
            if isinstance(category.get("category"), dict)
            else {}
        )

        value = (
            first_present(
                category,
                "id",
                "categoryId",
                "category_id",
            )
            or first_present(
                nested,
                "id",
                "categoryId",
                "category_id",
            )
        )

        try:
            return int(value)
        except (TypeError, ValueError):
            return None


    @classmethod
    def _category_tour(
        cls,
        category: dict[str, Any],
    ) -> str | None:
        category_id = cls._category_id(category)

        if category_id in cls._ATP_CATEGORY_IDS:
            return "atp"
        if category_id in cls._WTA_CATEGORY_IDS:
            return "wta"
        if category_id == cls.CATEGORY_GRAND_SLAM:
            # Grand Slam is shared by men and women; classify each event later.
            return None

        text = " ".join(
            str(first_present(category, key) or "")
            for key in ("name", "slug", "title")
        ).lower()

        if any(token in text for token in ("wta", "women", "female")):
            return "wta"
        if any(
            token in text
            for token in ("atp", "challenger", "itf men", " men", "male")
        ):
            return "atp"
        return None

    @staticmethod
    def _event_text(raw: dict[str, Any]) -> str:
        tournament = (
            raw.get("tournament")
            if isinstance(raw.get("tournament"), dict)
            else {}
        )
        unique = (
            tournament.get("uniqueTournament")
            if isinstance(tournament.get("uniqueTournament"), dict)
            else {}
        )
        category = (
            tournament.get("category")
            if isinstance(tournament.get("category"), dict)
            else {}
        )
        fields = [
            raw.get("name"),
            raw.get("eventName"),
            raw.get("gender"),
            tournament.get("name"),
            tournament.get("slug"),
            unique.get("name"),
            unique.get("slug"),
            category.get("name"),
            category.get("slug"),
        ]
        return " ".join(str(value or "") for value in fields).lower()

    @classmethod
    def _event_tour(
        cls,
        raw: dict[str, Any],
        source_category_id: int | None,
        source_category_name: str = "",
    ) -> str | None:
        if source_category_id in cls._ATP_CATEGORY_IDS:
            return "atp"
        if source_category_id in cls._WTA_CATEGORY_IDS:
            return "wta"

        text = (
            cls._event_text(raw)
            + " "
            + str(source_category_name or "").lower()
        )

        if any(token in text for token in ("wta", "women", "woman", "female")):
            return "wta"
        if any(token in text for token in ("atp", " men", "men's", "male")):
            return "atp"

        if source_category_id == cls.CATEGORY_GRAND_SLAM:
            # TennisApi typically labels the women's draw explicitly while the
            # men's draw may use the bare tournament name. Only use this fallback
            # after all explicit gender/tour markers have been checked.
            return "atp"

        return None

    @classmethod
    def _is_singles_event(cls, raw: dict[str, Any]) -> bool:
        text = cls._event_text(raw)
        if any(
            token in text
            for token in ("doubles", "double", "mixed doubles", "mixed double")
        ):
            return False

        for side_key in ("homeTeam", "awayTeam", "player1", "player2"):
            side = raw.get(side_key)
            if not isinstance(side, dict):
                continue
            members = first_present(side, "players", "members", "subTeams")
            if isinstance(members, list) and len(members) > 1:
                return False
            name = str(side.get("name") or "")
            if "/" in name:
                return False

        return True

    def calendar_categories(self, day: date) -> list[dict[str, Any]]:
        key = day.isoformat()
        cached = self._category_cache.get(key)
        if cached is not None:
            return cached

        token = self._day_token(day)
        payload = self._get(
            f"/api/tennis/calendar/{token}/categories"
        )
        rows = self._response_rows(payload, "categories")

        self._category_cache[key] = rows
        return rows

    def category_events(
        self,
        category_id: int,
        day: date,
    ) -> list[dict[str, Any]]:
        cache_key = (day.isoformat(), int(category_id))
        cached = self._event_cache.get(cache_key)
        if cached is not None:
            return cached

        token = self._day_token(day)
        payload = self._get(
            f"/api/tennis/category/{category_id}/events/{token}"
        )
        rows = self._response_rows(payload, "events")

        self._event_cache[cache_key] = rows
        return rows

    @classmethod
    def _response_rows(cls, payload, key):
        """An unknown/error envelope must not masquerade as an empty day."""
        if isinstance(payload, list):
            if not all(isinstance(row, dict) for row in payload):
                raise ProviderError(f"Invalid {key} list entries")
            return payload
        if isinstance(payload, dict):
            if payload.get("error") or payload.get("success") is False:
                raise ProviderError(f"Provider reported an error for {key}")
            for name in (key, "data", "result", "results", "response"):
                value = payload.get(name)
                if isinstance(value, (list, dict)):
                    return cls._response_rows(value, key)
        raise ProviderError(f"Unrecognised {key} response; refusing to mark date complete")

    @staticmethod
    def _annotate_event(
        raw: dict[str, Any],
        category_id: int,
        category_name: str,
    ) -> dict[str, Any]:
        event = dict(raw)
        event["_tbt_source_category_id"] = category_id
        event["_tbt_source_category_name"] = category_name
        provider_event_id = first_present(
            raw,
            "id",
            "eventId",
            "event_id",
        )
        if provider_event_id not in (None, ""):
            event["_tbt_provider_event_id"] = str(provider_event_id)
            home = raw.get("homeTeam", {})
            away = raw.get("awayTeam", {})
            status = raw.get("status", {})
            if (isinstance(home, dict) and isinstance(away, dict) and
                    isinstance(status, dict) and home.get("id") and away.get("id") and
                    status.get("type") == "finished"):
                event["_tbt_event_identity"] = {
                    "event_id": str(provider_event_id), "home": str(home["id"]),
                    "away": str(away["id"]), "status": "finished"}
        return event

    def matches_for_day(
        self,
        tour: str,
        day: date,
        historical: bool,
    ) -> list[MatchRecord]:
        tour = tour.lower()
        if tour not in {"atp", "wta"}:
            raise ValueError("tour must be atp or wta")

        matches: list[MatchRecord] = []

        for category in self.calendar_categories(day):
            category_id = self._category_id(category)
            if category_id is None:
                continue

            nested_category = (
                category.get("category")
                if isinstance(
                    category.get("category"),
                    dict,
                )
                else {}
            )

            category_name = str(
                first_present(
                    category,
                    "name",
                    "title",
                    "slug",
                )
                or first_present(
                    nested_category,
                    "name",
                    "title",
                    "slug",
                )
                or ""
            )
            category_tour = self._category_tour(category)

            if category_tour is not None and category_tour != tour:
                continue

            for raw in self.category_events(category_id, day):
                if not self._is_singles_event(raw):
                    continue

                event_tour = self._event_tour(
                    raw,
                    category_id,
                    category_name,
                )
                if event_tour != tour:
                    continue

                event = self._annotate_event(
                    raw,
                    category_id,
                    category_name,
                )
                try:
                    match = self.normalize_match(
                        event,
                        tour=tour,
                        historical=historical,
                    )
                except ValueError as exc:
                    logger.warning(
                        "Skipping %s event with invalid required identity/date: %s",
                        tour.upper(),
                        exc,
                    )
                    continue

                matches.append(match)

        return merge_matches(matches)

    def upcoming(
        self,
        tour: str,
        start: date,
        end: date | None = None,
    ) -> list[MatchRecord]:
        end = end or start
        if end < start:
            raise ValueError("end must be on or after start")

        matches: list[MatchRecord] = []
        day = start
        while day <= end:
            matches.extend(
                self.matches_for_day(
                    tour,
                    day,
                    historical=False,
                )
            )
            day += timedelta(days=1)

        return merge_matches(matches)

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

    def historical_period(self, tour: str, start: date, end: date) -> list[MatchRecord]:
        """Inclusive bounded results window; category/event caches are shared by tours."""
        if end < start:
            raise ValueError("end must be on or after start")
        rows: list[MatchRecord] = []
        day = start
        while day <= end:
            rows.extend(
                match
                for match in self.matches_for_day(tour, day, historical=True)
                if match.is_completed
            )
            day += timedelta(days=1)
        return merge_matches(rows)

    def historical_year(
        self,
        tour: str,
        year: int,
    ) -> list[MatchRecord]:
        """Fetch real completed singles through the provider-confirmed daily flow.

        TennisApi retired the old flat daily endpoint and the /tennis/v2 calendar
        route is not available on the current RapidAPI product. The supported
        coverage path is calendar/categories -> category/events.
        """
        tour = tour.lower()
        if tour not in {"atp", "wta"}:
            raise ValueError("tour must be atp or wta")

        today = date.today()
        start = date(year, 1, 1)
        end = min(date(year, 12, 31), today)

        if start > today:
            return []

        matches: list[MatchRecord] = []
        day = start
        days_checked = 0
        days_with_categories = 0
        normalized_matches = 0

        while day <= end:
            days_checked += 1

            try:
                categories = self.calendar_categories(day)
                if categories:
                    days_with_categories += 1

                daily = self.matches_for_day(
                    tour,
                    day,
                    historical=True,
                )
            except ProviderError as exc:
                logger.warning(
                    "Skipping %s %s after provider error: %s",
                    tour.upper(),
                    day.isoformat(),
                    exc,
                )
                day += timedelta(days=1)
                continue

            normalized_matches += len(daily)

            for match in daily:
                if not match.is_completed or not match.winner_id:
                    continue
                matches.append(match)

            day += timedelta(days=1)

        logger.info(
            "RapidAPI %s %s: days=%s category_days=%s normalized=%s "
            "completed=%s via calendar/categories -> category/events",
            tour.upper(),
            year,
            days_checked,
            days_with_categories,
            normalized_matches,
            len(merge_matches(matches)),
        )

        if not matches:
            raise ProviderError(
                "TennisApi history returned zero completed matches for "
                f"{tour.upper()} {year}. "
                f"days_checked={days_checked}, "
                f"days_with_categories={days_with_categories}, "
                f"normalized_matches={normalized_matches}. "
                "Refusing to report a successful empty bootstrap."
            )

        return merge_matches(matches)

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

        def clean_text(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, float) and not math.isfinite(value):
                return ""
            text = str(value).strip()
            if text.lower() in {"nan", "none", "null", "<na>", "nat"}:
                return ""
            return text

        name = clean_text(name)
        player_id = clean_text(player_id)

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

        # Never infer a winner from player ordering or completed status.
        # Category/event payloads normally expose winnerCode; if the provider
        # omits a real winner signal, keep winner_id missing and exclude that row
        # from supervised training rather than manufacture a label.
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
            def normalized(alias: str, value: Any) -> float | None:
                alias_text = alias.lower()
                percent_hint = (
                    "pct" in alias_text
                    or "percent" in alias_text
                    or "percentage" in alias_text
                )
                return normalize_rate(
                    value,
                    percent_hint=percent_hint,
                )

            side_obj = stat.get(
                side
            )

            if isinstance(
                side_obj,
                dict,
            ):
                for alias in aliases:
                    if alias in side_obj:
                        value = normalized(
                            alias,
                            side_obj[
                                alias
                            ],
                        )
                        if value is not None:
                            return value

            for alias in aliases:
                for key in (
                    f"{side}_{alias}",
                    f"{alias}_{side}",
                ):
                    if key in stat:
                        value = normalized(
                            alias,
                            stat[
                                key
                            ],
                        )
                        if value is not None:
                            return value

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

        if not p1_id or not p2_id:
            raise ValueError("Missing required player identity")
        if p1_id == p2_id:
            raise ValueError("Invalid player identity: both sides have the same player ID")

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
        if status not in {"finished", "completed", "ended", "ft"}:
            winner_id = None

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
