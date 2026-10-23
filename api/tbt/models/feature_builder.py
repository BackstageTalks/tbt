from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable


from ..data.atp_leaderboards import ATP_LEADERBOARD_FEATURE_NAMES
from ..data.atp_rank_history import ATP_RANK_HISTORY_FEATURE_NAMES
from ..data.wta_rank_history import WTA_RANK_HISTORY_FEATURE_NAMES
from ..data.wta_season_stats import WTA_SEASON_FEATURE_NAMES
from ..schemas import MatchRecord
from ..utils import clamp, stable_hash
from .elo import dynamic_k, elo_expected, update_elo


FEATURE_STATE_SCHEMA_VERSION = 4

# Bound temporary Python dictionary allocations while retaining every historical
# training row. This is a memory batch size, NOT a training sample limit.
_TRAIN_FRAME_CHUNK_ROWS = 2048


EVIDENCE_FEATURE_NAMES = [
    "recent_history_depth", "recent_surface_history_depth",
    "serve_evidence_depth", "return_evidence_depth",
    "surface_serve_evidence_depth", "surface_return_evidence_depth",
]

FEATURE_NAMES = [
    "elo_diff",
    "surface_elo_diff",
    "elo_probability",
    "season_yelo_diff",
    "season_yelo_probability",
    "season_yelo_form_diff",
    "season_yelo_known_both",
    "experience_diff",
    "recent_form_diff",
    "medium_form_diff",
    "opponent_adjusted_form_diff",
    "atp_surface_opponent_form_diff",
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
    "surface_h2h_advantage",
    "surface_h2h_known",
    "serve_quality_diff",
    "return_quality_diff",
    "surface_serve_quality_diff",
    "surface_return_quality_diff",
    "stats_known_both",
    "surface_stats_known_both",
    "first_strike_serve_diff",
    "return_in_play_diff",
    "return_depth_diff",
    "break_point_serve_diff",
    "break_point_return_diff",
    "net_efficiency_diff",
    "aggression_balance_diff",
    "rich_charting_known_both",
    "sets_7d_advantage",
    "games_7d_advantage",
    "sets_14d_advantage",
    "games_14d_advantage",
    "score_workload_known_both",
    "deciding_set_advantage",
    "deciding_set_known_both",
    "lost_set1_recovery_advantage",
    "lost_set1_recovery_known_both",
    "closing_advantage",
    "closing_known_both",
    "round_form_diff",
    "round_form_known_both",
    "tournament_history_advantage",
    "tournament_history_known_both",
    "tournament_level",
    "best_of_five",
    "indoor",
    "tour_atp",
    "data_depth",
] + EVIDENCE_FEATURE_NAMES + ATP_LEADERBOARD_FEATURE_NAMES + ATP_RANK_HISTORY_FEATURE_NAMES + WTA_RANK_HISTORY_FEATURE_NAMES + WTA_SEASON_FEATURE_NAMES

# Match Charting specialist rates are retained in canonical history and in
# FeatureBuilder state for research / future coverage growth. Current paired
# walk-forward ablation (2023-2026) did not show robust prospective lift, so
# governed production retraining excludes these fields by default.
RICH_CHARTING_FEATURE_NAMES = [
    "first_strike_serve_diff",
    "return_in_play_diff",
    "return_depth_diff",
    "break_point_serve_diff",
    "break_point_return_diff",
    "net_efficiency_diff",
    "aggression_balance_diff",
    "rich_charting_known_both",
]


def stats_surface_key(surface: str) -> str:
    """Surface bucket used by performance statistics. Indoor hard shares the hard pool; indoor remains a separate feature."""
    value = str(surface or "unknown").strip().lower()
    return "hard" if value == "indoor_hard" else value


@dataclass
class RecentPerformance:
    played_at: datetime
    won: float
    expected: float
    surface: str
    serve_quality: float | None = None
    return_quality: float | None = None
    sets_played: float | None = None
    games_played: float | None = None
    deciding_set_played: float | None = None
    first_set_won: float | None = None
    second_set_won: float | None = None
    round_bucket: str = "unknown"
    tournament_key: str = ""
    first_strike_serve: float | None = None
    return_in_play: float | None = None
    return_depth: float | None = None
    break_point_serve: float | None = None
    break_point_return: float | None = None
    net_efficiency: float | None = None
    aggression_balance: float | None = None
    serve_points_total: float | None = None
    return_points_total: float | None = None
    surface_expected: float | None = None


@dataclass
class PlayerState:
    overall_elo: float = 1500.0
    matches: int = 0
    season_year: int | None = None
    season_yelo: float = 1500.0
    season_matches: int = 0
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

    def __init__(self, *, independent_serve_return: bool = False,
                 independent_direct_rates: bool = False,
                 point_weighted_quality: bool = False) -> None:
        # Artifact-controlled semantics preserve legacy and already-fitted candidates.
        self.independent_serve_return = bool(independent_serve_return)
        self.independent_direct_rates = bool(independent_direct_rates)
        self.point_weighted_quality = bool(point_weighted_quality)
        # Sequential, pre-match tour priors. [won points, total points].
        self.quality_baselines = defaultdict(lambda: [0., 0.])
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

        # Surface-specific H2H is kept separately so the ordinary lifetime H2H
        # contract stays stable. The state is strictly point-in-time: it is only
        # updated after a completed historical match has been snapshotted.
        self.surface_h2h: dict[
            tuple[str, str, str],
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
                "season_year": state.season_year,
                "season_yelo": float(state.season_yelo),
                "season_matches": int(state.season_matches),
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
                        "sets_played": item.sets_played,
                        "games_played": item.games_played,
                        "deciding_set_played": item.deciding_set_played,
                        "first_set_won": item.first_set_won,
                        "second_set_won": item.second_set_won,
                        "round_bucket": item.round_bucket,
                        "tournament_key": item.tournament_key,
                        "first_strike_serve": item.first_strike_serve,
                        "return_in_play": item.return_in_play,
                        "return_depth": item.return_depth,
                        "break_point_serve": item.break_point_serve,
                        "break_point_return": item.break_point_return,
                        "net_efficiency": item.net_efficiency,
                        "aggression_balance": item.aggression_balance,
                        "serve_points_total": item.serve_points_total,
                        "return_points_total": item.return_points_total,
                        "surface_expected": item.surface_expected,
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

        surface_h2h = [
            {
                "left": left,
                "right": right,
                "surface": surface,
                "wins_left": int(wins[0]),
                "wins_right": int(wins[1]),
            }
            for (left, right, surface), wins in sorted(self.surface_h2h.items())
        ]

        return {
            "schema_version": FEATURE_STATE_SCHEMA_VERSION,
            "independent_serve_return": self.independent_serve_return,
            "independent_direct_rates": self.independent_direct_rates,
            "point_weighted_quality": self.point_weighted_quality,
            "quality_baselines": [
                {"tour": tour, "surface": surface, "field": field,
                 "won": float(values[0]), "points": float(values[1])}
                for (tour, surface, field), values in sorted(self.quality_baselines.items())
            ],
            "players": players,
            "h2h": h2h,
            "surface_h2h": surface_h2h,
        }

    @classmethod
    def from_state(cls, payload: dict | None) -> "FeatureBuilder":
        builder = cls(
            independent_serve_return=bool(payload.get("independent_serve_return", False))
            if isinstance(payload, dict) else False,
            independent_direct_rates=bool(payload.get("independent_direct_rates", False))
            if isinstance(payload, dict) else False,
            point_weighted_quality=bool(payload.get("point_weighted_quality", False))
            if isinstance(payload, dict) else False,
        )
        if not isinstance(payload, dict):
            return builder
        version = int(payload.get("schema_version") or 0)
        if version not in {1, 2, 3, FEATURE_STATE_SCHEMA_VERSION}:
            raise ValueError(
                f"Unsupported FeatureBuilder state schema {version}; "
                f"expected 1, 2, 3 or {FEATURE_STATE_SCHEMA_VERSION}"
            )

        for raw in payload.get("quality_baselines") or []:
            if not isinstance(raw, dict):
                continue
            key = (str(raw.get("tour") or ""), str(raw.get("surface") or ""),
                   str(raw.get("field") or ""))
            won, points = float(raw.get("won") or 0), float(raw.get("points") or 0)
            if (key[0] in {"atp", "wta"} and key[1]
                    and key[2] in {"serve_quality", "return_quality"}
                    and math.isfinite(won) and math.isfinite(points)
                    and 0 <= won <= points):
                builder.quality_baselines[key] = [won, points]

        raw_players = payload.get("players")
        if isinstance(raw_players, dict):
            for key, raw in raw_players.items():
                if not isinstance(raw, dict):
                    continue
                state = PlayerState(
                    overall_elo=float(raw.get("overall_elo", 1500.0)),
                    matches=int(raw.get("matches", 0)),
                    season_year=(int(raw["season_year"]) if raw.get("season_year") is not None else None),
                    season_yelo=float(raw.get("season_yelo", 1500.0)),
                    season_matches=int(raw.get("season_matches", 0)),
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
                                sets_played=item.get("sets_played"),
                                games_played=item.get("games_played"),
                                deciding_set_played=item.get("deciding_set_played"),
                                first_set_won=item.get("first_set_won"),
                                second_set_won=item.get("second_set_won"),
                                round_bucket=str(item.get("round_bucket") or "unknown"),
                                tournament_key=str(item.get("tournament_key") or ""),
                                first_strike_serve=item.get("first_strike_serve"),
                                return_in_play=item.get("return_in_play"),
                                return_depth=item.get("return_depth"),
                                break_point_serve=item.get("break_point_serve"),
                                break_point_return=item.get("break_point_return"),
                                net_efficiency=item.get("net_efficiency"),
                                aggression_balance=item.get("aggression_balance"),
                                serve_points_total=item.get("serve_points_total"),
                                return_points_total=item.get("return_points_total"),
                                surface_expected=item.get("surface_expected"),
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

        raw_surface_h2h = payload.get("surface_h2h")
        if isinstance(raw_surface_h2h, list):
            for item in raw_surface_h2h:
                if not isinstance(item, dict):
                    continue
                left = str(item.get("left") or "")
                right = str(item.get("right") or "")
                surface = stats_surface_key(str(item.get("surface") or "unknown"))
                if not left or not right or surface == "unknown":
                    continue
                builder.surface_h2h[(left, right, surface)] = [
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

    @staticmethod
    def _season_yelo_values(state: PlayerState, now: datetime) -> tuple[float, int]:
        """Return point-in-time season Elo, resetting logically at each UTC year boundary."""
        if state.season_year != now.year:
            return 1500.0, 0
        return float(state.season_yelo), int(state.season_matches)

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
                and stats_surface_key(surface) != "unknown"
                and stats_surface_key(item.surface) != stats_surface_key(surface)
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

    @staticmethod
    def _atp_surface_opponent_form(
        state: PlayerState, now: datetime, surface: str,
    ) -> float:
        """Historical surface Elo residual; uses only pre-match expectations."""
        key = stats_surface_key(surface)
        if key == "unknown":
            return 0.
        numerator, denominator = 0., 6.
        for item in state.recent:
            if stats_surface_key(item.surface) != key or item.surface_expected is None:
                continue
            if not 0 <= float(item.surface_expected) <= 1:
                continue
            age_days = max((now - item.played_at).total_seconds() / 86400., 0.)
            weight = .5 ** (age_days / 120.)
            numerator += weight * (item.won - item.surface_expected)
            denominator += weight
        return numerator / denominator

    @classmethod
    def _stat_quality(
        cls,
        state: PlayerState,
        now: datetime,
        field_name: str,
        *,
        surface: str | None = None,
    ) -> float | None:
        observed = [
            getattr(
                item,
                field_name,
            )
            for item in state.recent
            if (
                not surface
                or stats_surface_key(surface) == "unknown"
                or stats_surface_key(item.surface) == stats_surface_key(surface)
            )
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
            surface=surface,
            prior=(
                sum(observed)
                / len(observed)
            ),
            prior_weight=5.0,
        )

    @staticmethod
    def _evidence_depth(state: PlayerState, now: datetime, surface: str) -> dict[str, float]:
        """Observed support from earlier UTC days; missing stats never count.

        Decay uses the point-weighted quality estimator's 120-day half-life.
        Old career depth must not conceal a lack of recent observations.
        """
        counts = dict.fromkeys(EVIDENCE_FEATURE_NAMES, 0.0)
        for item in state.recent:
            age = (now - item.played_at).total_seconds() / 86400.
            if (item.played_at.astimezone(timezone.utc).date() >= now.astimezone(timezone.utc).date()
                    or not 0 < age <= 365):
                continue
            weight = 0.5 ** (age / 120.)
            same_surface = (stats_surface_key(surface) != "unknown" and
                            stats_surface_key(item.surface) == stats_surface_key(surface))
            counts["recent_history_depth"] += weight
            if same_surface:
                counts["recent_surface_history_depth"] += weight
            for kind in ("serve", "return"):
                value = getattr(item, f"{kind}_quality", None)
                if value is not None and math.isfinite(float(value)) and 0 <= float(value) <= 1:
                    counts[f"{kind}_evidence_depth"] += weight
                    if same_surface:
                        counts[f"surface_{kind}_evidence_depth"] += weight
        return {name: min(value / 20., 1.) for name, value in counts.items()}

    def _quality_estimate(
        self, state: PlayerState, now: datetime, field_name: str, *,
        tour: str, surface: str | None = None,
    ) -> float | None:
        """Research-only point-weighted rate with point-in-time tour prior.

        Old artifacts and observations without verified denominators retain the
        existing recency-weighted estimator. Never infer a denominator from a
        percentage or use current/future matches as the prior.
        """
        fallback = self._stat_quality(state, now, field_name, surface=surface)
        if not self.point_weighted_quality or field_name not in {
                "serve_quality", "return_quality"}:
            return fallback
        key = stats_surface_key(surface) if surface else "all"
        baseline = self.quality_baselines.get((str(tour).lower(), key, field_name))
        if baseline is None or baseline[1] < 1000:
            baseline = self.quality_baselines.get((str(tour).lower(), "all", field_name))
        if baseline is None or baseline[1] < 1000:
            return fallback
        prior = baseline[0] / baseline[1]
        points_field = ("serve_points_total" if field_name == "serve_quality"
                        else "return_points_total")
        numerator, denominator = 200. * prior, 200.
        with_rates, with_counts = 0, 0
        for item in state.recent:
            if surface and key != "unknown" and stats_surface_key(item.surface) != key:
                continue
            value = getattr(item, field_name)
            if value is None:
                continue
            with_rates += 1
            count = getattr(item, points_field, None)
            if (count is None or not math.isfinite(float(count))
                    or not 0 < float(count) <= 3000 or not 0 <= float(value) <= 1):
                continue
            with_counts += 1
            age = max((now - item.played_at).total_seconds() / 86400., 0.)
            weight = min(float(count), 250.) * (0.5 ** (age / 120.))
            numerator += weight * float(value)
            denominator += weight
        if not with_counts or 2 * with_counts < with_rates:
            return fallback
        return numerator / denominator

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

    def _surface_h2h_values(
        self,
        match: MatchRecord,
    ) -> tuple[float, float]:
        surface = stats_surface_key(match.surface)
        if surface == "unknown":
            return 0.0, 0.0
        key1 = self.player_key(match.tour, match.player1_id)
        key2 = self.player_key(match.tour, match.player2_id)
        left, right = sorted((key1, key2))
        wins_left, wins_right = self.surface_h2h[(left, right, surface)]
        if key1 == left:
            wins_p1, wins_p2 = wins_left, wins_right
        else:
            wins_p1, wins_p2 = wins_right, wins_left
        total = wins_p1 + wins_p2
        if total <= 0:
            return 0.0, 0.0
        # Beta(2,2) prior mirrors lifetime H2H shrinkage.
        share = (wins_p1 + 2.0) / (total + 4.0)
        return (share - 0.5) * 2.0, min(1.0, total / 4.0)

    @staticmethod
    def _metric_sum_in_window(
        state: PlayerState,
        now: datetime,
        days: float,
        field_name: str,
    ) -> float | None:
        cutoff_seconds = max(days, 0.0) * 86400.0
        values: list[float] = []
        for item in state.recent:
            age = (now - item.played_at).total_seconds()
            if age < 0.0 or age > cutoff_seconds:
                continue
            value = getattr(item, field_name, None)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and number >= 0.0:
                values.append(number)
        return sum(values) if values else None

    @staticmethod
    def _conditional_rate(
        state: PlayerState,
        now: datetime,
        *,
        condition,
        outcome,
        half_life_days: float = 180.0,
        prior: float = 0.5,
        prior_weight: float = 4.0,
    ) -> tuple[float | None, int]:
        numerator = prior * prior_weight
        denominator = prior_weight
        count = 0
        for item in state.recent:
            if not condition(item):
                continue
            value = outcome(item)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(number):
                continue
            age_days = max((now - item.played_at).total_seconds() / 86400.0, 0.0)
            weight = 0.5 ** (age_days / half_life_days)
            numerator += weight * clamp(number, 0.0, 1.0)
            denominator += weight
            count += 1
        if count == 0:
            return None, 0
        return numerator / denominator, count

    @staticmethod
    def _round_bucket(value: str) -> str:
        text = str(value or "").strip().lower().replace("-", " ").replace("_", " ")
        if not text:
            return "unknown"
        if "qual" in text:
            return "qualifying"
        if "final" in text and "semi" not in text and "quarter" not in text:
            return "final"
        if "semi" in text or text in {"sf"}:
            return "semifinal"
        if "quarter" in text or text in {"qf"}:
            return "quarterfinal"
        compact = text.replace("round of", "r").replace(" ", "")
        for token in ("r128", "r64", "r32", "r16"):
            if token in compact:
                return token
        return "other"

    @classmethod
    def _context_form(
        cls,
        state: PlayerState,
        now: datetime,
        *,
        round_bucket: str | None = None,
        tournament_key: str | None = None,
    ) -> tuple[float | None, int]:
        rows: list[RecentPerformance] = []
        for item in state.recent:
            if round_bucket and round_bucket != "unknown" and item.round_bucket != round_bucket:
                continue
            if tournament_key and item.tournament_key != tournament_key:
                continue
            rows.append(item)
        if not rows:
            return None, 0
        temp = deque(rows, maxlen=80)
        return (
            cls._decayed_average(
                temp, now, "won", 240.0, prior=0.5, prior_weight=5.0
            ),
            len(rows),
        )

    @staticmethod
    def _tournament_key(match: MatchRecord) -> str:
        value = str(match.tournament_id or "").strip()
        if value:
            return f"id:{value}"
        name = " ".join(str(match.tournament or "").strip().lower().split())
        return f"name:{name}" if name else ""

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

        if env.get(
            "training_eligible_weather"
        ) is not True:
            return {}

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

        y1, y1_n = self._season_yelo_values(p1, match.scheduled_at)
        y2, y2_n = self._season_yelo_values(p2, match.scheduled_at)
        season_yelo_p = elo_expected(y1, y2)

        s1 = p1.get_surface_elo(
            stats_surface_key(match.surface)
        )

        s2 = p2.get_surface_elo(
            stats_surface_key(match.surface)
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
            surface=stats_surface_key(match.surface),
        )

        sf2 = self._decayed_average(
            p2.recent,
            match.scheduled_at,
            "won",
            180.0,
            surface=stats_surface_key(match.surface),
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

        serve1 = self._quality_estimate(
            p1, match.scheduled_at, "serve_quality", tour=match.tour,
        )

        serve2 = self._quality_estimate(
            p2, match.scheduled_at, "serve_quality", tour=match.tour,
        )

        return1 = self._quality_estimate(
            p1, match.scheduled_at, "return_quality", tour=match.tour,
        )

        return2 = self._quality_estimate(
            p2, match.scheduled_at, "return_quality", tour=match.tour,
        )

        serve_known = serve1 is not None and serve2 is not None
        return_known = return1 is not None and return2 is not None
        stats_known = float(serve_known and return_known)
        serve_usable = serve_known if self.independent_serve_return else bool(stats_known)
        return_usable = return_known if self.independent_serve_return else bool(stats_known)

        surface_key = stats_surface_key(match.surface)
        surface_serve1 = self._quality_estimate(
            p1, match.scheduled_at, "serve_quality", tour=match.tour,
            surface=surface_key
        )
        surface_serve2 = self._quality_estimate(
            p2, match.scheduled_at, "serve_quality", tour=match.tour,
            surface=surface_key
        )
        surface_return1 = self._quality_estimate(
            p1, match.scheduled_at, "return_quality", tour=match.tour,
            surface=surface_key
        )
        surface_return2 = self._quality_estimate(
            p2, match.scheduled_at, "return_quality", tour=match.tour,
            surface=surface_key
        )
        surface_serve_known = (
            surface_key != "unknown"
            and surface_serve1 is not None
            and surface_serve2 is not None
        )
        surface_return_known = (
            surface_key != "unknown"
            and surface_return1 is not None
            and surface_return2 is not None
        )
        surface_stats_known = float(surface_serve_known and surface_return_known)
        surface_serve_usable = (
            surface_serve_known if self.independent_serve_return else bool(surface_stats_known)
        )
        surface_return_usable = (
            surface_return_known if self.independent_serve_return else bool(surface_stats_known)
        )

        # Match Charting Project specialist rates are stored on historical
        # matches, then decayed here exactly like serve/return quality. The
        # current match is never visible because snapshot() always precedes
        # update() in training/replay.
        rich_pairs: list[tuple[float | None, float | None]] = []
        rich_values: dict[str, tuple[float | None, float | None]] = {}
        for feature_name, state_field in (
            ("first_strike_serve_diff", "first_strike_serve"),
            ("return_in_play_diff", "return_in_play"),
            ("return_depth_diff", "return_depth"),
            ("break_point_serve_diff", "break_point_serve"),
            ("break_point_return_diff", "break_point_return"),
            ("net_efficiency_diff", "net_efficiency"),
            ("aggression_balance_diff", "aggression_balance"),
        ):
            value1 = self._stat_quality(p1, match.scheduled_at, state_field)
            value2 = self._stat_quality(p2, match.scheduled_at, state_field)
            rich_values[feature_name] = (value1, value2)
            rich_pairs.append((value1, value2))
        rich_charting_known_both = (
            sum(1 for left, right in rich_pairs if left is not None and right is not None)
            / float(len(rich_pairs))
        )

        surface_h2h_advantage, surface_h2h_known = self._surface_h2h_values(match)

        p1_sets_7d = self._metric_sum_in_window(p1, match.scheduled_at, 7.0, "sets_played")
        p2_sets_7d = self._metric_sum_in_window(p2, match.scheduled_at, 7.0, "sets_played")
        p1_games_7d = self._metric_sum_in_window(p1, match.scheduled_at, 7.0, "games_played")
        p2_games_7d = self._metric_sum_in_window(p2, match.scheduled_at, 7.0, "games_played")
        p1_sets_14d = self._metric_sum_in_window(p1, match.scheduled_at, 14.0, "sets_played")
        p2_sets_14d = self._metric_sum_in_window(p2, match.scheduled_at, 14.0, "sets_played")
        p1_games_14d = self._metric_sum_in_window(p1, match.scheduled_at, 14.0, "games_played")
        p2_games_14d = self._metric_sum_in_window(p2, match.scheduled_at, 14.0, "games_played")
        workload_known = float(
            None not in (
                p1_sets_7d, p2_sets_7d, p1_games_7d, p2_games_7d,
                p1_sets_14d, p2_sets_14d, p1_games_14d, p2_games_14d,
            )
        )
        sets_7d_advantage = (
            clamp((float(p2_sets_7d) - float(p1_sets_7d)) / 6.0, -2.0, 2.0)
            if workload_known else 0.0
        )
        games_7d_advantage = (
            clamp((float(p2_games_7d) - float(p1_games_7d)) / 50.0, -2.0, 2.0)
            if workload_known else 0.0
        )
        sets_14d_advantage = (
            clamp((float(p2_sets_14d) - float(p1_sets_14d)) / 10.0, -2.0, 2.0)
            if workload_known else 0.0
        )
        games_14d_advantage = (
            clamp((float(p2_games_14d) - float(p1_games_14d)) / 90.0, -2.0, 2.0)
            if workload_known else 0.0
        )

        dec1, dec1_n = self._conditional_rate(
            p1, match.scheduled_at,
            condition=lambda item: item.deciding_set_played is not None and float(item.deciding_set_played) >= 0.5,
            outcome=lambda item: item.won,
        )
        dec2, dec2_n = self._conditional_rate(
            p2, match.scheduled_at,
            condition=lambda item: item.deciding_set_played is not None and float(item.deciding_set_played) >= 0.5,
            outcome=lambda item: item.won,
        )
        deciding_known = float(dec1 is not None and dec2 is not None)

        rec1, rec1_n = self._conditional_rate(
            p1, match.scheduled_at,
            condition=lambda item: item.first_set_won is not None and float(item.first_set_won) < 0.5 and item.second_set_won is not None,
            outcome=lambda item: item.second_set_won,
        )
        rec2, rec2_n = self._conditional_rate(
            p2, match.scheduled_at,
            condition=lambda item: item.first_set_won is not None and float(item.first_set_won) < 0.5 and item.second_set_won is not None,
            outcome=lambda item: item.second_set_won,
        )
        recovery_known = float(rec1 is not None and rec2 is not None)

        close1, close1_n = self._conditional_rate(
            p1, match.scheduled_at,
            condition=lambda item: item.first_set_won is not None and float(item.first_set_won) >= 0.5,
            outcome=lambda item: item.won,
        )
        close2, close2_n = self._conditional_rate(
            p2, match.scheduled_at,
            condition=lambda item: item.first_set_won is not None and float(item.first_set_won) >= 0.5,
            outcome=lambda item: item.won,
        )
        closing_known = float(close1 is not None and close2 is not None)

        round_bucket = self._round_bucket(match.round_name)
        round1, round1_n = self._context_form(p1, match.scheduled_at, round_bucket=round_bucket)
        round2, round2_n = self._context_form(p2, match.scheduled_at, round_bucket=round_bucket)
        round_known = float(
            round_bucket != "unknown" and round1 is not None and round2 is not None
            and round1_n >= 2 and round2_n >= 2
        )

        tournament_key = self._tournament_key(match)
        tournament1, tournament1_n = self._context_form(
            p1, match.scheduled_at, tournament_key=tournament_key or None
        )
        tournament2, tournament2_n = self._context_form(
            p2, match.scheduled_at, tournament_key=tournament_key or None
        )
        tournament_known = float(
            bool(tournament_key) and tournament1 is not None and tournament2 is not None
            and tournament1_n >= 2 and tournament2_n >= 2
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

        # Static environment is known independently of weather.  Historical
        # archive weather remains research-only until genuine pre-match forecast
        # snapshots exist, but venue geometry/elevation is point-in-time safe.
        environment_known = float(
            current_lat is not None
            and current_lon is not None
            and current_alt is not None
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
            serve1 - serve2 if serve_usable else 0.0
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
                and serve_usable
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
                and serve_usable
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
            "season_yelo_diff": (
                y1 - y2
            ) / 400.0,
            "season_yelo_probability": (
                season_yelo_p
            ),
            "season_yelo_form_diff": (
                (y1 - p1.overall_elo)
                - (y2 - p2.overall_elo)
            ) / 400.0,
            "season_yelo_known_both": float(
                y1_n >= 5 and y2_n >= 5
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
            "atp_surface_opponent_form_diff": (
                self._atp_surface_opponent_form(p1, match.scheduled_at, match.surface)
                - self._atp_surface_opponent_form(p2, match.scheduled_at, match.surface)
            ) if match.tour.lower() == "atp" else 0.,
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
            "surface_h2h_advantage": surface_h2h_advantage,
            "surface_h2h_known": surface_h2h_known,
            "serve_quality_diff": (
                serve_diff if serve_usable else 0.0
            ),
            "return_quality_diff": (
                return1 - return2 if return_usable else 0.0
            ),
            "surface_serve_quality_diff": (
                float(surface_serve1) - float(surface_serve2)
                if surface_serve_usable else 0.0
            ),
            "surface_return_quality_diff": (
                float(surface_return1) - float(surface_return2)
                if surface_return_usable else 0.0
            ),
            "stats_known_both": (
                stats_known
            ),
            "surface_stats_known_both": surface_stats_known,
            "first_strike_serve_diff": (
                float(rich_values["first_strike_serve_diff"][0])
                - float(rich_values["first_strike_serve_diff"][1])
                if None not in rich_values["first_strike_serve_diff"] else 0.0
            ),
            "return_in_play_diff": (
                float(rich_values["return_in_play_diff"][0])
                - float(rich_values["return_in_play_diff"][1])
                if None not in rich_values["return_in_play_diff"] else 0.0
            ),
            "return_depth_diff": (
                float(rich_values["return_depth_diff"][0])
                - float(rich_values["return_depth_diff"][1])
                if None not in rich_values["return_depth_diff"] else 0.0
            ),
            "break_point_serve_diff": (
                float(rich_values["break_point_serve_diff"][0])
                - float(rich_values["break_point_serve_diff"][1])
                if None not in rich_values["break_point_serve_diff"] else 0.0
            ),
            "break_point_return_diff": (
                float(rich_values["break_point_return_diff"][0])
                - float(rich_values["break_point_return_diff"][1])
                if None not in rich_values["break_point_return_diff"] else 0.0
            ),
            "net_efficiency_diff": (
                float(rich_values["net_efficiency_diff"][0])
                - float(rich_values["net_efficiency_diff"][1])
                if None not in rich_values["net_efficiency_diff"] else 0.0
            ),
            "aggression_balance_diff": (
                float(rich_values["aggression_balance_diff"][0])
                - float(rich_values["aggression_balance_diff"][1])
                if None not in rich_values["aggression_balance_diff"] else 0.0
            ),
            "rich_charting_known_both": rich_charting_known_both,
            "sets_7d_advantage": sets_7d_advantage,
            "games_7d_advantage": games_7d_advantage,
            "sets_14d_advantage": sets_14d_advantage,
            "games_14d_advantage": games_14d_advantage,
            "score_workload_known_both": workload_known,
            "deciding_set_advantage": (float(dec1) - float(dec2)) if deciding_known else 0.0,
            "deciding_set_known_both": deciding_known,
            "lost_set1_recovery_advantage": (float(rec1) - float(rec2)) if recovery_known else 0.0,
            "lost_set1_recovery_known_both": recovery_known,
            "closing_advantage": (float(close1) - float(close2)) if closing_known else 0.0,
            "closing_known_both": closing_known,
            "round_form_diff": (float(round1) - float(round2)) if round_known else 0.0,
            "round_form_known_both": round_known,
            "tournament_history_advantage": (
                float(tournament1) - float(tournament2) if tournament_known else 0.0
            ),
            "tournament_history_known_both": tournament_known,
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
            **{
                name: min(left, right)
                for name, left, right in zip(
                    EVIDENCE_FEATURE_NAMES,
                    self._evidence_depth(p1, match.scheduled_at, match.surface).values(),
                    self._evidence_depth(p2, match.scheduled_at, match.surface).values(),
                )
            },
            "data_depth": (
                min(
                    p1.matches,
                    p2.matches,
                    50,
                )
                / 50.0
            ),
            **{
                name: 0.0
                for name in ATP_LEADERBOARD_FEATURE_NAMES + ATP_RANK_HISTORY_FEATURE_NAMES + WTA_RANK_HISTORY_FEATURE_NAMES + WTA_SEASON_FEATURE_NAMES
            },
        }

    @staticmethod
    def _extract_quality(
        stats: dict[
            str,
            float | None,
        ],
        prefix: str,
        *,
        independent_direct_rates: bool = False,
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

        # Old artifacts must retain their exact historical feature semantics.
        # For newly fitted candidates, an available point-weighted metric must
        # not be discarded merely because its complementary metric is missing.
        if independent_direct_rates:
            return (
                service if service is not None else serve,
                returns if returns is not None else ret,
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

        season_year = match.scheduled_at.year
        if p1.season_year != season_year:
            p1.season_year = season_year
            p1.season_yelo = 1500.0
            p1.season_matches = 0
        if p2.season_year != season_year:
            p2.season_year = season_year
            p2.season_yelo = 1500.0
            p2.season_matches = 0

        season_expected1 = elo_expected(
            p1.season_yelo,
            p2.overall_elo,
        )
        season_expected2 = elo_expected(
            p2.season_yelo,
            p1.overall_elo,
        )
        p1.season_yelo += dynamic_k(p1.season_matches) * (p1_won - season_expected1)
        p2.season_yelo += dynamic_k(p2.season_matches) * ((1.0 - p1_won) - season_expected2)
        p1.season_matches += 1
        p2.season_matches += 1

        expected_overall = elo_expected(
            p1.overall_elo,
            p2.overall_elo,
        )
        pre_surface = stats_surface_key(match.surface)
        surface_expected1 = (
            elo_expected(p1.get_surface_elo(pre_surface), p2.get_surface_elo(pre_surface))
            if pre_surface != "unknown" else None
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

        surface_key = stats_surface_key(match.surface)
        if surface_key != "unknown":
            old_s1 = (
                p1.surface_elo.get(
                    surface_key,
                    p1.overall_elo,
                )
            )

            old_s2 = (
                p2.surface_elo.get(
                    surface_key,
                    p2.overall_elo,
                )
            )

            sm1 = (
                p1.surface_matches.get(
                    surface_key,
                    0,
                )
            )

            sm2 = (
                p2.surface_matches.get(
                    surface_key,
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
                surface_key
            ] = ns1

            p2.surface_elo[
                surface_key
            ] = ns2

            p1.surface_matches[
                surface_key
            ] = (
                sm1 + 1
            )

            p2.surface_matches[
                surface_key
            ] = (
                sm2 + 1
            )

        (
            p1_serve,
            p1_return,
        ) = self._extract_quality(
            match.stats,
            "p1",
            independent_direct_rates=self.independent_direct_rates,
        )

        (
            p2_serve,
            p2_return,
        ) = self._extract_quality(
            match.stats,
            "p2",
            independent_direct_rates=self.independent_direct_rates,
        )

        stats = match.stats if isinstance(match.stats, dict) else {}
        total_sets = self._num(stats.get("total_sets"))
        total_games = self._num(stats.get("total_games"))
        deciding_set = self._num(stats.get("deciding_set"))
        p1_first_set = self._num(stats.get("p1_first_set_won"))
        p2_first_set = self._num(stats.get("p2_first_set_won"))
        p1_second_set = self._num(stats.get("p1_second_set_won"))
        p2_second_set = self._num(stats.get("p2_second_set_won"))
        round_bucket = self._round_bucket(match.round_name)
        tournament_key = self._tournament_key(match)

        def rich_rate(prefix: str, field_name: str) -> float | None:
            value = self._num(stats.get(f"{prefix}_{field_name}"))
            return value if value is not None and 0.0 <= value <= 1.0 else None

        p1_attack = rich_rate("p1", "attacking_points_rate")
        p1_unforced = rich_rate("p1", "unforced_error_rate")
        p2_attack = rich_rate("p2", "attacking_points_rate")
        p2_unforced = rich_rate("p2", "unforced_error_rate")
        p1_aggression = (
            p1_attack - p1_unforced
            if p1_attack is not None and p1_unforced is not None else None
        )
        p2_aggression = (
            p2_attack - p2_unforced
            if p2_attack is not None and p2_unforced is not None else None
        )

        def verified_points(prefix: str, metric: str) -> float | None:
            value = self._num(stats.get(f"{prefix}_{metric}_points_total"))
            return float(value) if value is not None and 0 < value <= 3000 else None

        p1_serve_n = verified_points("p1", "service")
        p1_return_n = verified_points("p1", "return")
        p2_serve_n = verified_points("p2", "service")
        p2_return_n = verified_points("p2", "return")

        p1.recent.append(
            RecentPerformance(
                match.scheduled_at,
                p1_won,
                expected_overall,
                stats_surface_key(match.surface),
                p1_serve,
                p1_return,
                total_sets,
                total_games,
                deciding_set,
                p1_first_set,
                p1_second_set,
                round_bucket,
                tournament_key,
                first_strike_serve=rich_rate("p1", "first_strike_serve_win"),
                return_in_play=rich_rate("p1", "return_in_play_rate"),
                return_depth=rich_rate("p1", "return_deep_rate"),
                break_point_serve=rich_rate("p1", "break_point_serve_win"),
                break_point_return=rich_rate("p1", "break_point_return_win"),
                net_efficiency=rich_rate("p1", "net_points_win"),
                aggression_balance=p1_aggression,
                serve_points_total=p1_serve_n,
                return_points_total=p1_return_n,
                surface_expected=surface_expected1,
            )
        )

        p2.recent.append(
            RecentPerformance(
                match.scheduled_at,
                1.0 - p1_won,
                1.0 - expected_overall,
                stats_surface_key(match.surface),
                p2_serve,
                p2_return,
                total_sets,
                total_games,
                deciding_set,
                p2_first_set,
                p2_second_set,
                round_bucket,
                tournament_key,
                first_strike_serve=rich_rate("p2", "first_strike_serve_win"),
                return_in_play=rich_rate("p2", "return_in_play_rate"),
                return_depth=rich_rate("p2", "return_deep_rate"),
                break_point_serve=rich_rate("p2", "break_point_serve_win"),
                break_point_return=rich_rate("p2", "break_point_return_win"),
                net_efficiency=rich_rate("p2", "net_points_win"),
                aggression_balance=p2_aggression,
                serve_points_total=p2_serve_n,
                return_points_total=p2_return_n,
                surface_expected=(1. - surface_expected1 if surface_expected1 is not None else None),
            )
        )

        # Update aggregate priors only *after* the current match's features
        # have been snapshotted; batch replay snapshots entire UTC days first.
        if self.point_weighted_quality:
            for quality, count, field in (
                (p1_serve, p1_serve_n, "serve_quality"),
                (p2_serve, p2_serve_n, "serve_quality"),
                (p1_return, p1_return_n, "return_quality"),
                (p2_return, p2_return_n, "return_quality"),
            ):
                if quality is None or count is None or not 0 <= quality <= 1:
                    continue
                for bucket in {"all", surface_key}:
                    totals = self.quality_baselines[(match.tour.lower(), bucket, field)]
                    totals[0] += float(quality) * count
                    totals[1] += count

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

        surface = stats_surface_key(match.surface)
        if surface != "unknown":
            surface_wins = self.surface_h2h[(left, right, surface)]
            if winner_key == left:
                surface_wins[0] += 1
            elif winner_key == right:
                surface_wins[1] += 1

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
    ) -> "pd.DataFrame":
        # pandas is required only for offline training-frame construction.
        # Keep the point-in-time snapshot/replay runtime importable by the
        # lightweight Azure Functions environment.
        import pandas as pd

        # The old implementation held ~1,000,000 feature dictionaries in RAM
        # alongside the history, replay state and resulting DataFrame. That
        # can OOM a GitHub-hosted training runner before the candidate fit.
        # Materialize bounded chunks, keeping the full chronology intact.
        columns = FEATURE_NAMES + [
            "surface_history_count", "target", "match_id",
            "scheduled_at", "tour", "surface",
        ]
        frames: list[pd.DataFrame] = []
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
                        "surface_history_count": min(self._state(oriented, True).surface_matches.get(stats_surface_key(oriented.surface), 0),
                                                     self._state(oriented, False).surface_matches.get(stats_surface_key(oriented.surface), 0)),
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
                if len(rows) >= _TRAIN_FRAME_CHUNK_ROWS:
                    frames.append(pd.DataFrame.from_records(rows, columns=columns))
                    rows.clear()
                    if len(frames) % 25 == 0:
                        print(
                            f"training_feature_snapshot: {len(frames) * _TRAIN_FRAME_CHUNK_ROWS} rows",
                            flush=True,
                        )

            for original in day_matches:
                self.update(
                    original
                )

        for match in completed:
            match_utc_date = (
                match.scheduled_at
                .astimezone(timezone.utc)
                .date()
            )

            if current_date is None:
                current_date = match_utc_date

            if (
                match_utc_date
                != current_date
            ):
                process_batch(
                    batch
                )

                batch = []

                current_date = match_utc_date

            batch.append(
                match
            )

        if batch:
            process_batch(
                batch
            )

        if rows:
            frames.append(pd.DataFrame.from_records(rows, columns=columns))
            rows.clear()
        # concat once; unlike a giant dictionary list, the intermediate
        # chunks have already released all row dictionaries.
        return (
            pd.concat(frames, ignore_index=True)
            if frames
            else pd.DataFrame(columns=columns)
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
