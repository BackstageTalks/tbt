"""Read-only Match Comparator runtime over a prebuilt JSON artifact."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Mapping

from ..data.atp_leaderboards import ATP_LEADERBOARD_FEATURE_NAMES, ATPLeaderboardPriors
from ..data.player_identity import normalize_player_name
from ..data.wta_season_stats import WTA_SEASON_FEATURE_NAMES, WTASeasonPriors
from ..models.feature_builder import FeatureBuilder, stats_surface_key
from ..models.portable_model import predict_probability
from ..schemas import MatchRecord


ALLOWED_TOURS = {"atp", "wta"}
ALLOWED_SURFACES = {"hard", "clay", "grass", "indoor_hard"}


class RuntimeComparatorError(ValueError):
    code = "comparator_error"


class RuntimePlayerNotFound(RuntimeComparatorError):
    code = "player_not_found"


class RuntimeAmbiguousPlayer(RuntimeComparatorError):
    code = "ambiguous_player"


class RuntimeArtifactStale(RuntimeComparatorError):
    code = "artifact_stale"


def _parse_time(value) -> datetime:
    result = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _players(artifact: Mapping) -> list[dict]:
    rows = artifact.get("players")
    if not isinstance(rows, list):
        raise RuntimeComparatorError("invalid player directory")
    return [row for row in rows if isinstance(row, dict)]


def search_players(artifact: Mapping, query: str, *, tour: str, limit: int = 12) -> list[dict]:
    tour = str(tour or "").strip().lower()
    key = normalize_player_name(query)
    if tour not in ALLOWED_TOURS or len(key) < 2:
        return []
    ranked = []
    for player in _players(artifact):
        if str(player.get("tour") or "").lower() != tour:
            continue
        names = [str(player.get("name") or "")] + [
            str(value) for value in (player.get("aliases") or []) if value
        ]
        normalized = [normalize_player_name(value) for value in names]
        if not any(key in value for value in normalized):
            continue
        exact = any(value == key for value in normalized)
        prefix = any(value.startswith(key) for value in normalized)
        ranked.append((
            not exact,
            not prefix,
            -int(player.get("matches_seen") or 0),
            str(player.get("name") or "").casefold(),
            player,
        ))
    ranked.sort(key=lambda row: row[:-1])
    return [
        {
            "player_id": str(row[-1].get("player_id") or ""),
            "name": str(row[-1].get("name") or ""),
            "tour": tour,
            "rank": row[-1].get("rank"),
            "matches_seen": int(row[-1].get("matches_seen") or 0),
        }
        for row in ranked[: max(1, min(int(limit), 25))]
    ]


def _resolve(artifact: Mapping, value: str, *, tour: str) -> dict:
    raw = str(value or "").strip()
    key = normalize_player_name(raw)
    matches = []
    for player in _players(artifact):
        if str(player.get("tour") or "").lower() != tour:
            continue
        # Search results submit canonical IDs. Direct typed names remain
        # supported, but never with fuzzy identity promotion.
        if raw and str(player.get("player_id") or "") == raw:
            return player
        names = [str(player.get("name") or "")] + [
            str(alias) for alias in (player.get("aliases") or []) if alias
        ]
        if any(normalize_player_name(name) == key for name in names):
            matches.append(player)
    unique = {str(row.get("player_id") or ""): row for row in matches}
    unique.pop("", None)
    if not unique:
        raise RuntimePlayerNotFound(f"player not found: {value}")
    if len(unique) != 1:
        raise RuntimeAmbiguousPlayer(f"ambiguous player: {value}")
    return next(iter(unique.values()))


def _artifact_freshness(artifact: Mapping, now: datetime) -> dict:
    generated = _parse_time(artifact.get("generated_at"))
    cutoff = _parse_time(artifact.get("cutoff_utc"))
    age_hours = max((now - generated).total_seconds() / 3600.0, 0.0)
    if age_hours > 36.0:
        raise RuntimeArtifactStale("comparator artifact older than 36 hours")
    return {
        "generated_at": generated.isoformat(),
        "cutoff_utc": cutoff.isoformat(),
        "age_hours": round(age_hours, 2),
        "stale": age_hours > 24.0,
    }


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
    band = (
        "high" if minimum >= 25 and surface_minimum >= 10
        else "medium" if minimum >= 10 and surface_minimum >= 4
        else "low"
    )
    return {"band": band, **samples}


def _player_stats(builder: FeatureBuilder, match: MatchRecord, *, first: bool) -> dict:
    state = builder._state(match, first)
    surface = stats_surface_key(match.surface)
    recent = list(state.recent)[-10:]
    surface_recent = [row for row in state.recent if stats_surface_key(row.surface) == surface][-10:]
    serve = builder._stat_quality(state, match.scheduled_at, "serve_quality", surface=surface)
    ret = builder._stat_quality(state, match.scheduled_at, "return_quality", surface=surface)
    return {
        "history_matches": int(state.matches),
        "surface_matches": int(state.surface_matches.get(surface, 0)),
        "overall_elo": round(float(state.overall_elo), 1),
        "surface_elo": round(float(state.get_surface_elo(surface)), 1),
        "recent_10": {
            "matches": len(recent),
            "wins": sum(float(row.won) >= .5 for row in recent),
        },
        "surface_recent_10": {
            "matches": len(surface_recent),
            "wins": sum(float(row.won) >= .5 for row in surface_recent),
        },
        "surface_serve_quality": None if serve is None else round(float(serve), 4),
        "surface_return_quality": None if ret is None else round(float(ret), 4),
    }


def compare_from_artifact(
    artifact: Mapping,
    *,
    player1: str,
    player2: str,
    tour: str,
    surface: str,
    best_of: int = 3,
    now: datetime | None = None,
) -> dict:
    if int(artifact.get("schema") or 0) != 1:
        raise RuntimeComparatorError("unsupported comparator artifact schema")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    freshness = _artifact_freshness(artifact, now)
    tour = str(tour or "").strip().lower()
    surface = str(surface or "").strip().lower()
    if tour not in ALLOWED_TOURS:
        raise RuntimeComparatorError("tour must be atp or wta")
    if surface not in ALLOWED_SURFACES:
        raise RuntimeComparatorError("unsupported surface")
    if best_of not in {3, 5} or (tour == "wta" and best_of == 5):
        raise RuntimeComparatorError("unsupported match format")

    left = _resolve(artifact, player1, tour=tour)
    right = _resolve(artifact, player2, tour=tour)
    left_id = str(left.get("player_id") or "")
    right_id = str(right.get("player_id") or "")
    if left_id == right_id:
        raise RuntimeComparatorError("players must be different")

    builder = FeatureBuilder.from_state(artifact.get("feature_state"))
    for player_id in (left_id, right_id):
        if builder.player_key(tour, player_id) not in builder.players:
            raise RuntimePlayerNotFound("player has no point-in-time feature state")

    match = MatchRecord(
        match_id=f"compare:{tour}:{left_id}:{right_id}:{surface}:{best_of}",
        tour=tour,
        scheduled_at=now,
        player1_id=left_id,
        player1_name=str(left.get("name") or player1),
        player2_id=right_id,
        player2_name=str(right.get("name") or player2),
        surface=surface,
        player1_rank=left.get("rank"),
        player2_rank=right.get("rank"),
        best_of=best_of,
        indoor=surface == "indoor_hard",
        status="upcoming",
    )
    features = builder.snapshot(match)

    atp_state = artifact.get("atp_leaderboards")
    if isinstance(atp_state, dict):
        features.update(ATPLeaderboardPriors.from_state(atp_state).features_for_match(match, current=True))
    wta_state = artifact.get("wta_season_stats")
    if isinstance(wta_state, dict):
        features.update(WTASeasonPriors.from_state(wta_state).features_for_match(match, current=True))

    model = artifact.get("model")
    if not isinstance(model, dict):
        raise RuntimeComparatorError("missing portable model")
    missing = [name for name in model.get("feature_names") or [] if name not in features]
    if missing:
        raise RuntimeComparatorError("missing model features: " + ", ".join(missing))
    probability = float(predict_probability(model, features))
    if not math.isfinite(probability) or not 0.0 < probability < 1.0:
        raise RuntimeComparatorError("invalid model probability")
    p1, p2 = probability, 1.0 - probability
    winner = left if p1 >= p2 else right

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
        if abs(value) >= scale:
            factors.append({
                "label": label,
                "advantage_player_id": left_id if value >= 0 else right_id,
                "magnitude": round(abs(value / scale), 3),
            })
    factors.sort(key=lambda row: row["magnitude"], reverse=True)

    quality = _quality(builder, match)
    return {
        "schema": 1,
        "generated_at": now.isoformat(),
        "artifact": freshness,
        "model_version": str(model.get("model_version") or ""),
        "api_requests": 0,
        "canonical_read_only": True,
        "tour": tour,
        "surface": surface,
        "best_of": best_of,
        "winner": {
            "player_id": str(winner.get("player_id") or ""),
            "name": str(winner.get("name") or ""),
        },
        "confidence": {
            "model_probability": round(max(p1, p2), 6),
            "data_band": quality["band"],
        },
        "player1": {
            "player_id": left_id,
            "name": str(left.get("name") or ""),
            "rank": left.get("rank"),
            "probability": round(p1, 6),
            "fair_odds": round(1.0 / p1, 3),
            "stats": _player_stats(builder, match, first=True),
        },
        "player2": {
            "player_id": right_id,
            "name": str(right.get("name") or ""),
            "rank": right.get("rank"),
            "probability": round(p2, 6),
            "fair_odds": round(1.0 / p2, 3),
            "stats": _player_stats(builder, match, first=False),
        },
        "quality": quality,
        "factors": factors[:5],
    }
