from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from ..schemas import MatchRecord
from ..utils import clamp, stable_hash
from .elo import elo_expected, update_elo


FEATURE_STATE_SCHEMA_VERSION = 1


FEATURE_NAMES = [
    "elo_diff",
    "surface_elo_diff",
    "elo_probability",
    "experience_diff",
    "recent_form_diff",
    "medium_form_diff",
    "opponent_adjusted_form_diff",
    "surface_form_diff",
    "rank_advantage",
    "rank_known_both",
    "rest_advantage",
    "layoff_advantage",
    "fatigue_3d_advantage",
    "fatigue_7d_advantage",
    "travel_km_advantage",
    "travel_known",
    "altitude_change_advantage",
    "altitude_change_known",
    "weather_serve_interaction",
    "weather_known",
    "altitude_serve_interaction",
    "environment_known",
    "h2h_advantage",
    "serve_quality_diff",
    "return_quality_diff",
    "stats_known_both",
    "tournament_level",
    "best_of_five",
    "indoor",
    "tour_atp",
    "data_depth",
]


@dataclass
class RecentPerformance:
    played_at: datetime
    won: float
    expected: float
    surface: str
    serve_quality: float | None = None
    return_quality: float | None = None


@dataclass
class PlayerState:
    overall_elo: float = 1500.0
    matches: int = 0
    surface_elo: dict[str, float] = field(default_factory=dict)
    surface_matches: dict[str, int] = field(default_factory=dict)
    last_played: datetime | None = None
    last_latitude: float | None = None
    last_longitude: float | None = None
    last_altitude_m: float | None = None
    recent: deque[RecentPerformance] = field(
        default_factory=lambda: deque(maxlen=80)
    )

    def get_surface_elo(
        self,
        surface: str,
    ) -> float:
        if surface == "unknown":
            return self.overall_elo

        observed = self.surface_matches.get(
            surface,
            0,
        )

        raw = self.surface_elo.get(
            surface,
            self.overall_elo,
        )

        # Partial pooling: surface Elo starts close to overall and gains
        # independence with data.
        weight = observed / (
            observed + 8.0
        )

        return (
            weight * raw
            + (1.0 - weight) * self.overall_elo
        )


class FeatureBuilder:
    """Sequential point-in-time feature engine.

    Features are always computed before updating player state with the
    match result.

    During training, all matches on the same calendar day are
    snapshotted before any result from that day is applied. This
    conservative batching prevents same-day leakage when historical
    providers only expose date-level timestamps.
    """

    def __init__(self) -> None:
        self.players: dict[
            str,
            PlayerState,
        ] = defaultdict(
            PlayerState
        )

        self.h2h: dict[
            tuple[str, str],
            list[int],
        ] = defaultdict(
            lambda: [0, 0]
        )

    @staticmethod
    def _state_datetime(value: str | datetime | None) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            result = value
        else:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)

    def export_state(self) -> dict:
        """Serialize replay state without pickling defaultdict factories.

        The payload is intentionally plain Python/JSON-compatible data so a model
        artifact can carry the complete archived Elo/form/H2H state after rolling
        history has been removed from Supabase.
        """
        players: dict[str, dict] = {}
        for key, state in self.players.items():
            players[str(key)] = {
                "overall_elo": float(state.overall_elo),
                "matches": int(state.matches),
                "surface_elo": {str(k): float(v) for k, v in state.surface_elo.items()},
                "surface_matches": {str(k): int(v) for k, v in state.surface_matches.items()},
                "last_played": (
                    state.last_played.astimezone(timezone.utc).isoformat()
                    if state.last_played is not None
                    else None
                ),
                "last_latitude": state.last_latitude,
                "last_longitude": state.last_longitude,
                "last_altitude_m": state.last_altitude_m,
                "recent": [
                    {
                        "played_at": item.played_at.astimezone(timezone.utc).isoformat(),
                        "won": float(item.won),
                        "expected": float(item.expected),
                        "surface": str(item.surface),
                        "serve_quality": item.serve_quality,
                        "return_quality": item.return_quality,
                    }
                    for item in state.recent
                ],
            }

        h2h = [
            {
                "left": left,
                "right": right,
                "wins_left": int(wins[0]),
                "wins_right": int(wins[1]),
            }
            for (left, right), wins in sorted(self.h2h.items())
        ]

        return {
            "schema_version": FEATURE_STATE_SCHEMA_VERSION,
            "players": players,
            "h2h": h2h,
        }

    @classmethod
    def from_state(cls, payload: dict | None) -> "FeatureBuilder":
        builder = cls()
        if not isinstance(payload, dict):
            return builder
        version = int(payload.get("schema_version") or 0)
        if version != FEATURE_STATE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported FeatureBuilder state schema {version}; "
                f"expected {FEATURE_STATE_SCHEMA_VERSION}"
            )

        raw_players = payload.get("players")
        if isinstance(raw_players, dict):
            for key, raw in raw_players.items():
                if not isinstance(raw, dict):
                    continue
                state = PlayerState(
                    overall_elo=float(raw.get("overall_elo", 1500.0)),
                    matches=int(raw.get("matches", 0)),
                    surface_elo={
                        str(k): float(v)
                        for k, v in (raw.get("surface_elo") or {}).items()
                    },
                    surface_matches={
                        str(k): int(v)
                        for k, v in (raw.get("surface_matches") or {}).items()
                    },
                    last_played=cls._state_datetime(raw.get("last_played")),
                    last_latitude=raw.get("last_latitude"),
                    last_longitude=raw.get("last_longitude"),
                    last_altitude_m=raw.get("last_altitude_m"),
                )
                recent = raw.get("recent")
                if isinstance(recent, list):
                    for item in recent[-80:]:
                        if not isinstance(item, dict):
                            continue
                        played_at = cls._state_datetime(item.get("played_at"))
                        if played_at is None:
                            continue
                        state.recent.append(
                            RecentPerformance(
                                played_at=played_at,
                                won=float(item.get("won", 0.0)),
                                expected=float(item.get("expected", 0.5)),
                                surface=str(item.get("surface") or "unknown"),
                                serve_quality=item.get("serve_quality"),
                                return_quality=item.get("return_quality"),
                            )
                        )
                builder.players[str(key)] = state

        raw_h2h = payload.get("h2h")
        if isinstance(raw_h2h, list):
            for item in raw_h2h:
                if not isinstance(item, dict):
                    continue
                left = str(item.get("left") or "")
                right = str(item.get("right") or "")
                if not left or not right:
                    continue
                builder.h2h[(left, right)] = [
                    int(item.get("wins_left", 0)),
                    int(item.get("wins_right", 0)),
                ]

        return builder

    @staticmethod
    def player_key(
        tour: str,
        player_id: str,
    ) -> str:
        return (
            f"{tour.lower()}:"
            f"{player_id}"
        )

    def _state(
        self,
        match: MatchRecord,
        first: bool,
    ) -> PlayerState:
        player_id = (
            match.player1_id
            if first
            else match.player2_id
        )

        return self.players[
            self.player_key(
                match.tour,
                player_id,
            )
        ]

    @staticmethod
    def _decayed_average(
        recent: deque[
            RecentPerformance
        ],
        now: datetime,
        field_name: str,
        half_life_days: float,
        surface: str | None = None,
        prior: float = 0.5,
        prior_weight: float = 4.0,
    ) -> float:
        numerator = (
            prior * prior_weight
        )

        denominator = prior_weight

        for item in recent:
            if (
                surface
                and surface != "unknown"
                and item.surface != surface
            ):
                continue

            age_days = max(
                (
                    now - item.played_at
                ).total_seconds()
                / 86400.0,
                0.0,
            )

            weight = (
                0.5
                ** (
                    age_days
                    / half_life_days
                )
            )

            value = getattr(
                item,
                field_name,
            )

            if value is None:
                continue

            numerator += (
                weight
                * float(value)
            )

            denominator += weight

        return (
            numerator / denominator
            if denominator
            else prior
        )

    @classmethod
    def _form(
        cls,
        state: PlayerState,
        now: datetime,
        half_life: float,
    ) -> float:
        return cls._decayed_average(
            state.recent,
            now,
            "won",
            half_life,
        )

    @classmethod
    def _opponent_adjusted_form(
        cls,
        state: PlayerState,
        now: datetime,
    ) -> float:
        # Residual result above/below Elo expectation, shrunk toward
        # zero.
        numerator = 0.0
        denominator = 6.0

        for item in state.recent:
            age_days = max(
                (
                    now - item.played_at
                ).total_seconds()
                / 86400.0,
                0.0,
            )

            weight = (
                0.5
                ** (
                    age_days / 60.0
                )
            )

            numerator += (
                weight
                * (
                    item.won
                    - item.expected
                )
            )

            denominator += weight

        return (
            numerator / denominator
        )

    @classmethod
    def _stat_quality(
        cls,
        state: PlayerState,
        now: datetime,
        field_name: str,
    ) -> float | None:
        observed = [
            getattr(
                item,
                field_name,
            )
            for item in state.recent
        ]

        observed = [
            value
            for value in observed
            if value is not None
        ]

        if not observed:
            return None

        return cls._decayed_average(
            state.recent,
            now,
            field_name,
            half_life_days=120.0,
            prior=(
                sum(observed)
                / len(observed)
            ),
            prior_weight=5.0,
        )

    def _h2h_advantage(
        self,
        match: MatchRecord,
    ) -> float:
        key1 = self.player_key(
            match.tour,
            match.player1_id,
        )

        key2 = self.player_key(
            match.tour,
            match.player2_id,
        )

        left, right = sorted(
            (
                key1,
                key2,
            )
        )

        (
            wins_left,
            wins_right,
        ) = self.h2h[
            (
                left,
                right,
            )
        ]

        if key1 == left:
            wins_p1 = wins_left
            wins_p2 = wins_right

        else:
            wins_p1 = wins_right
            wins_p2 = wins_left

        # Beta(2,2) prior strongly shrinks tiny H2H samples.
        p1_share = (
            (
                wins_p1
                + 2.0
            )
            / (
                wins_p1
                + wins_p2
                + 4.0
            )
        )

        return (
            (
                p1_share
                - 0.5
            )
            * 2.0
        )

    @staticmethod
    def _level_value(
        level: str,
    ) -> float:
        text = (
            level or ""
        ).lower()

        if (
            "grand slam" in text
            or "slam" in text
        ):
            return 1.0

        if (
            "1000" in text
            or "masters" in text
        ):
            return 0.8

        if "500" in text:
            return 0.6

        if "250" in text:
            return 0.45

        if "challenger" in text:
            return 0.25

        if "itf" in text:
            return 0.1

        return 0.35

    @staticmethod
    def _rest_days(
        state: PlayerState,
        now: datetime,
    ) -> float:
        if state.last_played is None:
            return 14.0

        return clamp(
            (
                now
                - state.last_played
            ).total_seconds()
            / 86400.0,
            0.0,
            180.0,
        )

    @staticmethod
    def _layoff_penalty(
        days: float,
    ) -> float:
        # No penalty up to ~3 weeks, increasing softly afterwards.
        return math.log1p(
            max(
                days - 21.0,
                0.0,
            )
        )

    @staticmethod
    def _matches_in_window(
        state: PlayerState,
        now: datetime,
        days: float,
    ) -> int:
        cutoff_seconds = (
            max(
                days,
                0.0,
            )
            * 86400.0
        )

        return sum(
            1
            for item in state.recent
            if (
                0.0
                <= (
                    now
                    - item.played_at
                ).total_seconds()
                <= cutoff_seconds
            )
        )

    @staticmethod
    def _environment(
        match: MatchRecord,
    ) -> dict:
        """Read optional point-in-time environment enrichment.

        Expected shape inside provider_payload:

        {
          "_tbt_environment": {
            "venue": {
              "latitude": ...,
              "longitude": ...,
              "elevation_m": ...
            },
            "weather": {
              "temperature_c": ...,
              "relative_humidity_pct": ...,
              "wind_speed_kmh": ...,
              "wind_gusts_kmh": ...,
              "surface_pressure_hpa": ...
            }
          }
        }

        Missing values stay missing; they are never guessed or
        backfilled here.
        """

        raw = (
            match.provider_payload
            if isinstance(
                match.provider_payload,
                dict,
            )
            else {}
        )

        env = raw.get(
            "_tbt_environment"
        )

        return (
            env
            if isinstance(
                env,
                dict,
            )
            else {}
        )

    @staticmethod
    def _num(
        value,
    ) -> float | None:
        try:
            if value in (
                None,
                "",
            ):
                return None

            return float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

    @classmethod
    def _venue_values(
        cls,
        match: MatchRecord,
    ) -> tuple[
        float | None,
        float | None,
        float | None,
    ]:
        env = cls._environment(
            match
        )

        venue = env.get(
            "venue"
        )

        if not isinstance(
            venue,
            dict,
        ):
            return (
                None,
                None,
                None,
            )

        return (
            cls._num(
                venue.get(
                    "latitude"
                )
            ),
            cls._num(
                venue.get(
                    "longitude"
                )
            ),
            cls._num(
                venue.get(
                    "elevation_m"
                )
            ),
        )

    @classmethod
    def _weather_values(
        cls,
        match: MatchRecord,
    ) -> dict[
        str,
        float | None,
    ]:
        env = cls._environment(
            match
        )

        weather = env.get(
            "weather"
        )

        if not isinstance(
            weather,
            dict,
        ):
            return {}

        return {
            "temperature_c": cls._num(
                weather.get(
                    "temperature_c"
                )
            ),
            "relative_humidity_pct": cls._num(
                weather.get(
                    "relative_humidity_pct"
                )
            ),
            "wind_speed_kmh": cls._num(
                weather.get(
                    "wind_speed_kmh"
                )
            ),
            "wind_gusts_kmh": cls._num(
                weather.get(
                    "wind_gusts_kmh"
                )
            ),
            "surface_pressure_hpa": cls._num(
                weather.get(
                    "surface_pressure_hpa"
                )
            ),
        }

    @staticmethod
    def _haversine_km(
        lat1: float | None,
        lon1: float | None,
        lat2: float | None,
        lon2: float | None,
    ) -> float | None:
        if None in (
            lat1,
            lon1,
            lat2,
            lon2,
        ):
            return None

        radius = 6371.0088

        phi1 = math.radians(
            float(lat1)
        )

        phi2 = math.radians(
            float(lat2)
        )

        dphi = math.radians(
            float(lat2)
            - float(lat1)
        )

        dlambda = math.radians(
            float(lon2)
            - float(lon1)
        )

        a = (
            math.sin(
                dphi / 2.0
            )
            ** 2
            + math.cos(phi1)
            * math.cos(phi2)
            * math.sin(
                dlambda / 2.0
            )
            ** 2
        )

        return (
            2.0
            * radius
            * math.asin(
                math.sqrt(a)
            )
        )

    def snapshot(
        self,
        match: MatchRecord,
    ) -> dict[str, float]:
        p1 = self._state(
            match,
            True,
        )

        p2 = self._state(
            match,
            False,
        )

        s1 = p1.get_surface_elo(
            match.surface
        )

        s2 = p2.get_surface_elo(
            match.surface
        )

        blended1 = (
            0.48
            * p1.overall_elo
            + 0.52
            * s1
        )

        blended2 = (
            0.48
            * p2.overall_elo
            + 0.52
            * s2
        )

        elo_p = elo_expected(
            blended1,
            blended2,
        )

        f1_short = self._form(
            p1,
            match.scheduled_at,
            30.0,
        )

        f2_short = self._form(
            p2,
            match.scheduled_at,
            30.0,
        )

        f1_med = self._form(
            p1,
            match.scheduled_at,
            120.0,
        )

        f2_med = self._form(
            p2,
            match.scheduled_at,
            120.0,
        )

        sf1 = self._decayed_average(
            p1.recent,
            match.scheduled_at,
            "won",
            180.0,
            surface=match.surface,
        )

        sf2 = self._decayed_average(
            p2.recent,
            match.scheduled_at,
            "won",
            180.0,
            surface=match.surface,
        )

        r1 = match.player1_rank
        r2 = match.player2_rank

        rank_known = float(
            r1 is not None
            and r2 is not None
            and r1 > 0
            and r2 > 0
        )

        rank_advantage = (
            (
                math.log1p(r2)
                - math.log1p(r1)
            )
            if rank_known
            else 0.0
        )

        rest1 = self._rest_days(
            p1,
            match.scheduled_at,
        )

        rest2 = self._rest_days(
            p2,
            match.scheduled_at,
        )

        rest_advantage = clamp(
            (
                math.log1p(rest1)
                - math.log1p(rest2)
            ),
            -2.0,
            2.0,
        )

        layoff_advantage = clamp(
            (
                self._layoff_penalty(
                    rest2
                )
                - self._layoff_penalty(
                    rest1
                )
            ),
            -3.0,
            3.0,
        )

        # Objective fatigue/workload features. Positive values favour
        # player 1, i.e. player 2 has carried the heavier recent match
        # load.
        p1_3d = self._matches_in_window(
            p1,
            match.scheduled_at,
            3.0,
        )

        p2_3d = self._matches_in_window(
            p2,
            match.scheduled_at,
            3.0,
        )

        p1_7d = self._matches_in_window(
            p1,
            match.scheduled_at,
            7.0,
        )

        p2_7d = self._matches_in_window(
            p2,
            match.scheduled_at,
            7.0,
        )

        fatigue_3d_advantage = clamp(
            (
                p2_3d
                - p1_3d
            )
            / 3.0,
            -2.0,
            2.0,
        )

        fatigue_7d_advantage = clamp(
            (
                p2_7d
                - p1_7d
            )
            / 5.0,
            -2.0,
            2.0,
        )

        (
            current_lat,
            current_lon,
            current_alt,
        ) = self._venue_values(
            match
        )

        travel1 = self._haversine_km(
            p1.last_latitude,
            p1.last_longitude,
            current_lat,
            current_lon,
        )

        travel2 = self._haversine_km(
            p2.last_latitude,
            p2.last_longitude,
            current_lat,
            current_lon,
        )

        travel_known = (
            travel1 is not None
            and travel2 is not None
        )

        travel_km_advantage = (
            clamp(
                (
                    float(travel2)
                    - float(travel1)
                )
                / 5000.0,
                -2.0,
                2.0,
            )
            if travel_known
            else 0.0
        )

        alt_change1 = (
            abs(
                current_alt
                - p1.last_altitude_m
            )
            if (
                current_alt is not None
                and p1.last_altitude_m
                is not None
            )
            else None
        )

        alt_change2 = (
            abs(
                current_alt
                - p2.last_altitude_m
            )
            if (
                current_alt is not None
                and p2.last_altitude_m
                is not None
            )
            else None
        )

        altitude_change_known = (
            alt_change1 is not None
            and alt_change2 is not None
        )

        altitude_change_advantage = (
            clamp(
                (
                    float(
                        alt_change2
                    )
                    - float(
                        alt_change1
                    )
                )
                / 2000.0,
                -2.0,
                2.0,
            )
            if altitude_change_known
            else 0.0
        )

        serve1 = self._stat_quality(
            p1,
            match.scheduled_at,
            "serve_quality",
        )

        serve2 = self._stat_quality(
            p2,
            match.scheduled_at,
            "serve_quality",
        )

        return1 = self._stat_quality(
            p1,
            match.scheduled_at,
            "return_quality",
        )

        return2 = self._stat_quality(
            p2,
            match.scheduled_at,
            "return_quality",
        )

        stats_known = float(
            serve1 is not None
            and serve2 is not None
            and return1 is not None
            and return2 is not None
        )

        weather = self._weather_values(
            match
        )

        wind = weather.get(
            "wind_speed_kmh"
        )

        temperature = weather.get(
            "temperature_c"
        )

        humidity = weather.get(
            "relative_humidity_pct"
        )

        weather_known = (
            wind is not None
            and temperature is not None
            and humidity is not None
        )

        environment_known = float(
            current_lat is not None
            and current_lon is not None
            and current_alt is not None
            and weather_known
        )

        # Raw weather is identical for both players and therefore cannot
        # create a meaningful side advantage after deterministic
        # orientation. We expose only physically interpretable
        # interactions with the pre-match serve-strength difference.
        #
        # They are zero when either component is genuinely unavailable.
        # The explicit *_known features below allow the model to
        # distinguish "neutral value" from "missing source data".
        serve_diff = (
            serve1 - serve2
            if stats_known
            else 0.0
        )

        weather_serve_interaction = (
            clamp(
                serve_diff
                * (
                    (
                        float(wind)
                        - 10.0
                    )
                    / 20.0
                ),
                -3.0,
                3.0,
            )
            if (
                weather_known
                and stats_known
            )
            else 0.0
        )

        altitude_serve_interaction = (
            clamp(
                serve_diff
                * (
                    float(
                        current_alt
                    )
                    / 2000.0
                ),
                -3.0,
                3.0,
            )
            if (
                current_alt is not None
                and stats_known
            )
            else 0.0
        )

        return {
            "elo_diff": (
                p1.overall_elo
                - p2.overall_elo
            )
            / 400.0,
            "surface_elo_diff": (
                s1 - s2
            )
            / 400.0,
            "elo_probability": (
                elo_p
            ),
            "experience_diff": clamp(
                (
                    math.log1p(
                        p1.matches
                    )
                    - math.log1p(
                        p2.matches
                    )
                )
                / 4.0,
                -2.0,
                2.0,
            ),
            "recent_form_diff": (
                f1_short
                - f2_short
            ),
            "medium_form_diff": (
                f1_med
                - f2_med
            ),
            "opponent_adjusted_form_diff": (
                self._opponent_adjusted_form(
                    p1,
                    match.scheduled_at,
                )
                - self._opponent_adjusted_form(
                    p2,
                    match.scheduled_at,
                )
            ),
            "surface_form_diff": (
                sf1 - sf2
            ),
            "rank_advantage": clamp(
                rank_advantage,
                -5.0,
                5.0,
            ),
            "rank_known_both": (
                rank_known
            ),
            "rest_advantage": (
                rest_advantage
            ),
            "layoff_advantage": (
                layoff_advantage
            ),
            "fatigue_3d_advantage": (
                fatigue_3d_advantage
            ),
            "fatigue_7d_advantage": (
                fatigue_7d_advantage
            ),
            "travel_km_advantage": (
                travel_km_advantage
            ),
            "travel_known": float(
                travel_known
            ),
            "altitude_change_advantage": (
                altitude_change_advantage
            ),
            "altitude_change_known": float(
                altitude_change_known
            ),
            "weather_serve_interaction": (
                weather_serve_interaction
            ),
            "weather_known": float(
                weather_known
            ),
            "altitude_serve_interaction": (
                altitude_serve_interaction
            ),
            "environment_known": (
                environment_known
            ),
            "h2h_advantage": (
                self._h2h_advantage(
                    match
                )
            ),
            "serve_quality_diff": (
                serve1 - serve2
                if stats_known
                else 0.0
            ),
            "return_quality_diff": (
                return1 - return2
                if stats_known
                else 0.0
            ),
            "stats_known_both": (
                stats_known
            ),
            "tournament_level": (
                self._level_value(
                    match.tournament_level
                )
            ),
            "best_of_five": float(
                match.best_of == 5
            ),
            "indoor": float(
                match.indoor is True
                or match.surface
                == "indoor_hard"
            ),
            "tour_atp": float(
                match.tour.lower()
                == "atp"
            ),
            "data_depth": (
                min(
                    p1.matches,
                    p2.matches,
                    50,
                )
                / 50.0
            ),
        }

    @staticmethod
    def _extract_quality(
        stats: dict[
            str,
            float | None,
        ],
        prefix: str,
    ) -> tuple[
        float | None,
        float | None,
    ]:
        # Prefer point-weighted service/return rates from event enrichment.
        service = stats.get(f"{prefix}_service_points_won")
        returns = stats.get(f"{prefix}_return_points_won")
        if service is not None and returns is not None:
            return service, returns
        # These are intentionally generic. Missing provider stats are
        # not imputed from future data.
        first_win = stats.get(
            f"{prefix}_first_serve_win"
        )

        second_win = stats.get(
            f"{prefix}_second_serve_win"
        )

        ace_rate = stats.get(
            f"{prefix}_ace_rate"
        )

        return_points = stats.get(
            f"{prefix}_return_points_won"
        )

        break_conv = stats.get(
            f"{prefix}_break_points_won"
        )

        serve_parts = [
            value
            for value in (
                first_win,
                second_win,
                ace_rate,
            )
            if value is not None
        ]

        return_parts = [
            value
            for value in (
                return_points,
                break_conv,
            )
            if value is not None
        ]

        serve = (
            sum(
                serve_parts
            )
            / len(
                serve_parts
            )
            if serve_parts
            else None
        )

        ret = (
            sum(
                return_parts
            )
            / len(
                return_parts
            )
            if return_parts
            else None
        )

        return (
            serve,
            ret,
        )

    def update(
        self,
        match: MatchRecord,
    ) -> None:
        if not match.is_completed:
            return

        p1 = self._state(
            match,
            True,
        )

        p2 = self._state(
            match,
            False,
        )

        p1_won = float(
            match.winner_id
            == match.player1_id
        )

        expected_overall = elo_expected(
            p1.overall_elo,
            p2.overall_elo,
        )

        new1, new2 = update_elo(
            p1.overall_elo,
            p2.overall_elo,
            p1_won,
            p1.matches,
            p2.matches,
            multiplier=(
                1.0
                + 0.15
                * self._level_value(
                    match.tournament_level
                )
            ),
        )

        if (
            match.surface
            != "unknown"
        ):
            old_s1 = (
                p1.surface_elo.get(
                    match.surface,
                    p1.overall_elo,
                )
            )

            old_s2 = (
                p2.surface_elo.get(
                    match.surface,
                    p2.overall_elo,
                )
            )

            sm1 = (
                p1.surface_matches.get(
                    match.surface,
                    0,
                )
            )

            sm2 = (
                p2.surface_matches.get(
                    match.surface,
                    0,
                )
            )

            ns1, ns2 = update_elo(
                old_s1,
                old_s2,
                p1_won,
                sm1,
                sm2,
                multiplier=0.9,
            )

            p1.surface_elo[
                match.surface
            ] = ns1

            p2.surface_elo[
                match.surface
            ] = ns2

            p1.surface_matches[
                match.surface
            ] = (
                sm1 + 1
            )

            p2.surface_matches[
                match.surface
            ] = (
                sm2 + 1
            )

        (
            p1_serve,
            p1_return,
        ) = self._extract_quality(
            match.stats,
            "p1",
        )

        (
            p2_serve,
            p2_return,
        ) = self._extract_quality(
            match.stats,
            "p2",
        )

        p1.recent.append(
            RecentPerformance(
                match.scheduled_at,
                p1_won,
                expected_overall,
                match.surface,
                p1_serve,
                p1_return,
            )
        )

        p2.recent.append(
            RecentPerformance(
                match.scheduled_at,
                1.0 - p1_won,
                1.0 - expected_overall,
                match.surface,
                p2_serve,
                p2_return,
            )
        )

        (
            p1.overall_elo,
            p2.overall_elo,
        ) = (
            new1,
            new2,
        )

        p1.matches += 1
        p2.matches += 1

        p1.last_played = (
            match.scheduled_at
        )

        p2.last_played = (
            match.scheduled_at
        )

        (
            venue_lat,
            venue_lon,
            venue_alt,
        ) = self._venue_values(
            match
        )

        if (
            venue_lat is not None
            and venue_lon is not None
        ):
            p1.last_latitude = (
                venue_lat
            )

            p1.last_longitude = (
                venue_lon
            )

            p2.last_latitude = (
                venue_lat
            )

            p2.last_longitude = (
                venue_lon
            )

        if venue_alt is not None:
            p1.last_altitude_m = (
                venue_alt
            )

            p2.last_altitude_m = (
                venue_alt
            )

        key1 = self.player_key(
            match.tour,
            match.player1_id,
        )

        key2 = self.player_key(
            match.tour,
            match.player2_id,
        )

        left, right = sorted(
            (
                key1,
                key2,
            )
        )

        wins = self.h2h[
            (
                left,
                right,
            )
        ]

        winner_key = self.player_key(
            match.tour,
            match.winner_id or "",
        )

        if winner_key == left:
            wins[0] += 1

        elif winner_key == right:
            wins[1] += 1

    @staticmethod
    def orient_for_training(
        match: MatchRecord,
    ) -> tuple[
        MatchRecord,
        int,
    ]:
        """Break provider winner-order bias deterministically.

        Some historical tennis APIs always store the winner as
        `player1`. Training on that ordering would make the target
        trivially predictable.

        We independently orient each match from a stable hash and
        compute the label after orientation.
        """

        oriented = (
            match.swapped()
            if (
                stable_hash(
                    match.match_id
                )
                % 2
            )
            else match
        )

        target = int(
            oriented.winner_id
            == oriented.player1_id
        )

        return (
            oriented,
            target,
        )

    def build_training_frame(
        self,
        matches: Iterable[
            MatchRecord
        ],
    ) -> pd.DataFrame:
        completed = sorted(
            (
                match
                for match in matches
                if match.is_completed
            ),
            key=lambda match: (
                match.scheduled_at,
                match.match_id,
            ),
        )

        rows: list[
            dict[
                str,
                float
                | int
                | str
                | datetime,
            ]
        ] = []

        current_date = None

        batch: list[
            MatchRecord
        ] = []

        def process_batch(
            day_matches: list[
                MatchRecord
            ],
        ) -> None:
            # Snapshot every match before applying any result from this
            # calendar day.
            for original in day_matches:
                (
                    oriented,
                    target,
                ) = self.orient_for_training(
                    original
                )

                features = self.snapshot(
                    oriented
                )

                rows.append(
                    {
                        **features,
                        "surface_history_count": min(self._state(oriented, True).surface_matches.get(oriented.surface, 0),
                                                     self._state(oriented, False).surface_matches.get(oriented.surface, 0)),
                        "target": (
                            target
                        ),
                        "match_id": (
                            original.match_id
                        ),
                        "scheduled_at": (
                            original.scheduled_at
                        ),
                        "tour": (
                            original.tour.lower()
                        ),
                        "surface": (
                            original.surface
                        ),
                    }
                )

            for original in day_matches:
                self.update(
                    original
                )

        for match in completed:
            if current_date is None:
                current_date = (
                    match.event_date
                )

            if (
                match.event_date
                != current_date
            ):
                process_batch(
                    batch
                )

                batch = []

                current_date = (
                    match.event_date
                )

            batch.append(
                match
            )

        if batch:
            process_batch(
                batch
            )

        columns = (
            FEATURE_NAMES
            + [
                "surface_history_count",
                "target",
                "match_id",
                "scheduled_at",
                "tour",
                "surface",
            ]
        )

        return pd.DataFrame(
            rows,
            columns=columns,
        )

    def replay(
        self,
        matches: Iterable[
            MatchRecord
        ],
        before: datetime | None = None,
    ) -> None:
        completed = sorted(
            (
                match
                for match in matches
                if match.is_completed
            ),
            key=lambda match: (
                match.scheduled_at,
                match.match_id,
            ),
        )

        for match in completed:
            if (
                before is not None
                and match.scheduled_at
                >= before
            ):
                continue

            self.update(
                match
            )
