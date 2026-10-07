from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Iterable

import pandas as pd

from ..data.player_identity import normalize_player_name
from ..models.feature_builder import FeatureBuilder, FEATURE_NAMES, stats_surface_key
from ..models.portable_export import export_portable_model
from ..schemas import MatchRecord
from .data_quality import audit_history
from .training import _enforce_rank_provenance


ALLOWED_TOURS = {"atp", "wta"}
ALLOWED_SURFACES = {"hard", "clay", "grass", "indoor_hard"}


class ComparatorError(ValueError):
    code = "comparator_error"


class PlayerNotFoundError(ComparatorError):
    code = "player_not_found"


class AmbiguousPlayerError(ComparatorError):
    code = "ambiguous_player"


class ComparatorCoverageError(ComparatorError):
    code = "insufficient_data"


@dataclass(frozen=True)
class ComparatorPlayer:
    tour: str
    player_id: str
    name: str
    rank: int | None
    aliases: tuple[str, ...]
    matches_seen: int


def _latest_rank(value) -> int | None:
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return None
    return rank if rank > 0 else None


class PlayerDirectory:
    """Fail-closed name resolver built only from canonical MatchRecord history."""

    def __init__(self, players: Iterable[ComparatorPlayer]):
        self.players = tuple(players)
        by_id = {}
        by_name = defaultdict(list)
        for player in self.players:
            by_id[(player.tour, player.player_id)] = player
            for raw in (player.name, *player.aliases):
                key = normalize_player_name(raw)
                if key:
                    by_name[(player.tour, key)].append(player)
        self._by_id = by_id
        self._by_name = {
            key: tuple({p.player_id: p for p in rows}.values())
            for key, rows in by_name.items()
        }

    @classmethod
    def from_history(cls, history: Iterable[MatchRecord]) -> "PlayerDirectory":
        rows = {}
        aliases = defaultdict(set)
        for match in history:
            tour = str(match.tour or "").strip().lower()
            if tour not in ALLOWED_TOURS:
                continue
            for idx in (1, 2):
                player_id = str(getattr(match, f"player{idx}_id") or "").strip()
                name = str(getattr(match, f"player{idx}_name") or "").strip()
                if not player_id or not name:
                    continue
                key = (tour, player_id)
                aliases[key].add(name)
                rank = _latest_rank(getattr(match, f"player{idx}_rank"))
                existing = rows.get(key)
                candidate = {
                    "tour": tour,
                    "player_id": player_id,
                    "name": name,
                    "rank": rank,
                    "last_seen": match.scheduled_at,
                    "matches_seen": int((existing or {}).get("matches_seen", 0)) + 1,
                }
                if existing and existing["last_seen"] > match.scheduled_at:
                    candidate["name"] = existing["name"]
                    candidate["rank"] = existing["rank"]
                    candidate["last_seen"] = existing["last_seen"]
                elif existing and rank is None:
                    candidate["rank"] = existing["rank"]
                rows[key] = candidate

        players = []
        for key, row in rows.items():
            canonical_name = row["name"]
            players.append(ComparatorPlayer(
                tour=row["tour"],
                player_id=row["player_id"],
                name=canonical_name,
                rank=row["rank"],
                aliases=tuple(sorted(a for a in aliases[key] if a != canonical_name)),
                matches_seen=row["matches_seen"],
            ))
        return cls(sorted(players, key=lambda p: (p.tour, p.name.casefold(), p.player_id)))

    def resolve(self, value: str, *, tour: str) -> ComparatorPlayer:
        tour = str(tour or "").strip().lower()
        if tour not in ALLOWED_TOURS:
            raise ComparatorError("tour must be atp or wta")
        key = normalize_player_name(value)
        if not key:
            raise PlayerNotFoundError("empty player name")
        rows = self._by_name.get((tour, key), ())
        if not rows:
            raise PlayerNotFoundError(f"player not found: {value}")
        if len(rows) != 1:
            raise AmbiguousPlayerError(f"ambiguous player name: {value}")
        return rows[0]

    def get(self, *, tour: str, player_id: str) -> ComparatorPlayer:
        player = self._by_id.get((str(tour).lower(), str(player_id)))
        if player is None:
            raise PlayerNotFoundError(f"unknown player id: {player_id}")
        return player

    def search(self, query: str, *, tour: str, limit: int = 12) -> list[ComparatorPlayer]:
        tour = str(tour or "").strip().lower()
        key = normalize_player_name(query)
        if tour not in ALLOWED_TOURS or len(key) < 2:
            return []
        ranked = []
        for player in self.players:
            if player.tour != tour:
                continue
            names = (player.name, *player.aliases)
            normalized = [normalize_player_name(name) for name in names]
            if key not in " ".join(normalized):
                continue
            prefix = any(name.startswith(key) for name in normalized)
            exact = any(name == key for name in normalized)
            ranked.append((not exact, not prefix, -player.matches_seen, player.name.casefold(), player))
        ranked.sort(key=lambda row: row[:-1])
        return [row[-1] for row in ranked[: max(1, min(int(limit), 25))]]


def build_pre_match_builder(history: Iterable[MatchRecord], *, now: datetime) -> tuple[FeatureBuilder, datetime, list[MatchRecord]]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    replay = [match for match in history if match.scheduled_at < cutoff]
    replay, _ = audit_history(replay, now=now)
    replay, _ = _enforce_rank_provenance(replay)
    builder = FeatureBuilder()
    builder.replay(replay, before=cutoff)
    return builder, cutoff, replay


def _quality(builder: FeatureBuilder, match: MatchRecord) -> dict:
    p1 = builder._state(match, True)
    p2 = builder._state(match, False)
    surface = stats_surface_key(match.surface)
    samples = {
        "player1_matches": int(p1.matches),
        "player2_matches": int(p2.matches),
        "player1_surface_matches": int(p1.surface_matches.get(surface, 0)),
        "player2_surface_matches": int(p2.surface_matches.get(surface, 0)),
    }
    minimum = min(samples["player1_matches"], samples["player2_matches"])
    surface_minimum = min(samples["player1_surface_matches"], samples["player2_surface_matches"])
    if minimum >= 25 and surface_minimum >= 10:
        band = "high"
    elif minimum >= 10 and surface_minimum >= 4:
        band = "medium"
    else:
        band = "low"
    return {"band": band, **samples}


def _player_summary(builder: FeatureBuilder, match: MatchRecord, first: bool) -> dict:
    state = builder._state(match, first)
    surface = stats_surface_key(match.surface)
    recent = list(state.recent)[-10:]
    surface_recent = [row for row in state.recent if stats_surface_key(row.surface) == surface][-10:]
    wins = sum(float(row.won) >= .5 for row in recent)
    surface_wins = sum(float(row.won) >= .5 for row in surface_recent)
    serve = builder._stat_quality(state, match.scheduled_at, "serve_quality", surface=surface)
    ret = builder._stat_quality(state, match.scheduled_at, "return_quality", surface=surface)
    return {
        "history_matches": int(state.matches),
        "surface_matches": int(state.surface_matches.get(surface, 0)),
        "overall_elo": round(float(state.overall_elo), 1),
        "surface_elo": round(float(state.get_surface_elo(surface)), 1),
        "recent_10": {"matches": len(recent), "wins": int(wins)},
        "surface_recent_10": {"matches": len(surface_recent), "wins": int(surface_wins)},
        "surface_serve_quality": None if serve is None else round(float(serve), 4),
        "surface_return_quality": None if ret is None else round(float(ret), 4),
    }


def compare(
    model,
    history: Iterable[MatchRecord],
    *,
    player1: str,
    player2: str,
    tour: str,
    surface: str,
    best_of: int = 3,
    now: datetime | None = None,
    atp_leaderboards=None,
    wta_season_stats=None,
) -> dict:
    """Exact champion-model comparison for an arbitrary same-tour singles matchup.

    No provider/API calls are made. All state is reconstructed from canonical
    completed history strictly before the current UTC day, matching production
    prediction leakage rules.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    tour = str(tour or "").strip().lower()
    surface = str(surface or "").strip().lower()
    if tour not in ALLOWED_TOURS:
        raise ComparatorError("tour must be atp or wta")
    if surface not in ALLOWED_SURFACES:
        raise ComparatorError("unsupported surface")
    if best_of not in {3, 5}:
        raise ComparatorError("best_of must be 3 or 5")
    if tour == "wta" and best_of == 5:
        raise ComparatorError("WTA best_of=5 is not supported")

    materialized = list(history)
    directory = PlayerDirectory.from_history(materialized)
    left = directory.resolve(player1, tour=tour)
    right = directory.resolve(player2, tour=tour)
    if left.player_id == right.player_id:
        raise ComparatorError("players must be different")

    builder, cutoff, _ = build_pre_match_builder(materialized, now=now)
    for player in (left, right):
        if builder.player_key(tour, player.player_id) not in builder.players:
            raise ComparatorCoverageError(f"no pre-cutoff state for {player.name}")

    synthetic = MatchRecord(
        match_id=f"compare:{tour}:{left.player_id}:{right.player_id}:{surface}:{best_of}",
        tour=tour,
        scheduled_at=now,
        player1_id=left.player_id,
        player1_name=left.name,
        player2_id=right.player_id,
        player2_name=right.name,
        surface=surface,
        player1_rank=left.rank,
        player2_rank=right.rank,
        status="upcoming",
        best_of=best_of,
        indoor=surface == "indoor_hard",
    )
    features = builder.snapshot(synthetic)
    if atp_leaderboards is not None:
        features.update(atp_leaderboards.features_for_match(synthetic, current=True))
    if wta_season_stats is not None:
        features.update(wta_season_stats.features_for_match(synthetic, current=True))

    feature_names = list(getattr(model, "feature_names", None) or FEATURE_NAMES)
    missing = [name for name in feature_names if name not in features]
    if missing:
        raise ComparatorCoverageError("model feature sources unavailable: " + ", ".join(missing))

    probability = float(model.predict_proba(pd.DataFrame([features], columns=feature_names))[0])
    if not math.isfinite(probability) or not 0.0 < probability < 1.0:
        raise ComparatorError("model returned invalid probability")
    p1 = probability
    p2 = 1.0 - probability
    winner = left if p1 >= p2 else right
    confidence = max(p1, p2)

    factor_specs = (
        ("Sila na povrchu", "surface_elo_diff", .12),
        ("Celková výkonnosť", "elo_diff", .12),
        ("Aktuálna forma", "recent_form_diff", .08),
        ("Servis", "serve_quality_diff", .04),
        ("Return", "return_quality_diff", .04),
        ("H2H", "h2h_advantage", .10),
    )
    factors = []
    for label, name, scale in factor_specs:
        value = float(features.get(name, 0.0) or 0.0)
        if abs(value) < scale:
            continue
        factors.append({
            "label": label,
            "advantage_player_id": left.player_id if value >= 0 else right.player_id,
            "magnitude": round(abs(value / scale), 3),
        })
    factors.sort(key=lambda row: row["magnitude"], reverse=True)

    quality = _quality(builder, synthetic)
    return {
        "schema": 1,
        "generated_at": now.isoformat(),
        "cutoff_utc": cutoff.isoformat(),
        "model_version": str(getattr(model, "version", "") or ""),
        "api_requests": 0,
        "canonical_read_only": True,
        "tour": tour,
        "surface": surface,
        "best_of": best_of,
        "winner": {"player_id": winner.player_id, "name": winner.name},
        "confidence": {
            "model_probability": round(confidence, 6),
            "data_band": quality["band"],
        },
        "player1": {
            "player_id": left.player_id,
            "name": left.name,
            "rank": left.rank,
            "probability": round(p1, 6),
            "fair_odds": round(1.0 / p1, 3),
            "stats": _player_summary(builder, synthetic, True),
        },
        "player2": {
            "player_id": right.player_id,
            "name": right.name,
            "rank": right.rank,
            "probability": round(p2, 6),
            "fair_odds": round(1.0 / p2, 3),
            "stats": _player_summary(builder, synthetic, False),
        },
        "quality": quality,
        "factors": factors[:5],
        "feature_contract": {
            "count": len(feature_names),
            "point_in_time": True,
            "historical_date_mode": False,
        },
    }


def build_serving_artifact(
    model,
    history: Iterable[MatchRecord],
    *,
    now: datetime | None = None,
    atp_leaderboards=None,
    wta_season_stats=None,
) -> dict:
    """Build a self-contained read-only comparator artifact for the web runtime."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    materialized = list(history)
    builder, cutoff, replay = build_pre_match_builder(materialized, now=now)
    directory = PlayerDirectory.from_history(replay)

    players = [
        {
            "tour": player.tour,
            "player_id": player.player_id,
            "name": player.name,
            "rank": player.rank,
            "aliases": list(player.aliases),
            "matches_seen": player.matches_seen,
        }
        for player in directory.players
        if builder.player_key(player.tour, player.player_id) in builder.players
    ]

    feature_names = set(getattr(model, "feature_names", None) or FEATURE_NAMES)
    requires_atp = bool(feature_names & set(ATP_LEADERBOARD_FEATURE_NAMES))
    requires_wta = bool(feature_names & set(WTA_SEASON_FEATURE_NAMES))
    if requires_atp and atp_leaderboards is None:
        raise ComparatorCoverageError("champion requires ATP leaderboard priors")
    if requires_wta and wta_season_stats is None:
        raise ComparatorCoverageError("champion requires WTA season priors")

    artifact = {
        "schema": 1,
        "generated_at": now.isoformat(),
        "cutoff_utc": cutoff.isoformat(),
        "model": export_portable_model(model),
        "feature_state": builder.export_state(),
        "players": players,
        "source": {
            "canonical_matches_replayed": len(replay),
            "players": len(players),
            "point_in_time": True,
            "canonical_read_only": True,
            "provider_requests_per_user_compare": 0,
        },
    }
    if atp_leaderboards is not None:
        artifact["atp_leaderboards"] = atp_leaderboards.export_state()
    if wta_season_stats is not None:
        artifact["wta_season_stats"] = wta_season_stats.export_state()
    return artifact
