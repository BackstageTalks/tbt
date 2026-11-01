"""Audited, read-only point-in-time ace/double-fault projections for Match Comparator.

The champion winner model and canonical writer are untouched. BO3/BO5 duration
normalization is allowed only with observed completed-match game counts; unknown
cross-format evidence is never imputed as if it were the selected format.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
from typing import Mapping

from ..models.feature_builder import stats_surface_key
from .ace_selection import _projection

MARKETS = ("aces", "double_faults")
MAX_SAMPLES_PER_PLAYER = 160
MIN_LENGTH_SAMPLES = 20
MAX_STAT_AGE_DAYS = 540
MIN_EFFECTIVE_SAMPLES = 3.0


def _count(value):
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _format(value):
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result in (3, 5) else None


def _avg(values, minimum=1):
    return sum(values) / len(values) if len(values) >= minimum else None


def _length_mean(lengths, tour, surface, fmt):
    if fmt not in (3, 5):
        return None
    scope = lengths.get(tour) or {}
    for key in (stats_surface_key(surface), "all"):
        row = (scope.get(key) or {}).get(str(fmt)) or {}
        if int(row.get("matches") or 0) >= MIN_LENGTH_SAMPLES:
            return _count(row.get("mean_games"))
    return None


def build_market_state(replay, allowed_keys: set[str], cutoff: datetime) -> dict:
    if cutoff.tzinfo is None:
        raise ValueError("market cutoff must be timezone-aware")
    cutoff = cutoff.astimezone(timezone.utc)
    rows = defaultdict(list)
    totals = defaultdict(list)
    formatted = defaultdict(list)
    lengths = defaultdict(list)
    latest = {}
    complete = 0

    for match in sorted(replay, key=lambda x: (x.scheduled_at, str(x.match_id))):
        if match.scheduled_at >= cutoff or str(match.status).lower() != "completed":
            continue
        tour = str(match.tour or "").lower()
        if tour not in ("atp", "wta"):
            continue
        surface = stats_surface_key(match.surface)
        fmt = _format(match.best_of)
        raw = match.stats if isinstance(match.stats, dict) else {}
        games = _count(raw.get("total_games"))
        # A missing match length is not evidence for cross-format normalization.
        if games is not None and 10 <= games <= 75 and fmt is not None:
            lengths[(tour, surface, fmt)].append(games)
            lengths[(tour, "all", fmt)].append(games)
        else:
            games = None
        values = {
            field: (_count(raw.get("p1_" + field)), _count(raw.get("p2_" + field)))
            for field in MARKETS
        }
        if all(v is None for pair in values.values() for v in pair):
            continue
        complete += 1
        moment = match.scheduled_at.astimezone(timezone.utc).isoformat()
        latest[tour] = moment
        for field, pair in values.items():
            totals[(tour, field)].extend(v for v in pair if v is not None)
            if fmt is not None:
                formatted[(tour, fmt, field)].extend(v for v in pair if v is not None)
        common = {
            "scheduled_at": moment,
            "surface": surface,
            "best_of": fmt,
            "total_games": games,
        }
        for idx, player_id in enumerate((match.player1_id, match.player2_id)):
            key = f"{tour}:{player_id}"
            if key not in allowed_keys:
                continue
            record = dict(common)
            for field, pair in values.items():
                record["own_" + field] = pair[idx]
                record["opponent_" + field] = pair[1 - idx]
            rows[key].append(record)

    players = {}
    for key in sorted(allowed_keys):
        samples = rows.get(key, [])[-MAX_SAMPLES_PER_PLAYER:]
        players[key] = {
            "samples": samples,
            "sample_window": MAX_SAMPLES_PER_PLAYER,
            "last_stat_match": samples[-1]["scheduled_at"] if samples else None,
        }
    baselines = {
        tour: {field: _avg(totals[(tour, field)]) for field in MARKETS}
        for tour in ("atp", "wta")
    }
    format_baselines = {
        tour: {
            str(fmt): {
                field: _avg(formatted[(tour, fmt, field)], minimum=12)
                for field in MARKETS
            } for fmt in (3, 5)
        } for tour in ("atp", "wta")
    }
    format_lengths = {
        tour: {
            surface: {
                str(fmt): {
                    "matches": len(lengths[(tour, surface, fmt)]),
                    "mean_games": _avg(lengths[(tour, surface, fmt)]),
                } for fmt in (3, 5)
            } for surface in ("all", "hard", "clay", "grass", "unknown")
        } for tour in ("atp", "wta")
    }
    return {
        "schema": 2,
        "cutoff_utc": cutoff.isoformat(),
        "baselines": baselines,
        "format_baselines": format_baselines,
        "format_lengths": format_lengths,
        "players": players,
        "canonical_stat_matches": complete,
        "latest_stat_match_by_tour": latest,
        "provider_requests": 0,
    }


def _aligned_samples(rows: list[dict], tour: str, surface: str, fmt: int,
                     lengths: Mapping) -> list[dict]:
    target_games = _length_mean(lengths, tour, surface, fmt)
    aligned = []
    for row in rows:
        source_format = _format(row.get("best_of"))
        if source_format is None:
            continue
        games = _count(row.get("total_games"))
        # If the selected format differs, reliable actual games and target
        # duration calibration are both mandatory. Never silently treat BO3
        # per-match aces as a BO5 projection.
        if source_format != fmt and (target_games is None or games is None):
            continue
        scale = (target_games / games) if target_games and games and games >= 10 else 1.0
        if not (0.45 <= scale <= 2.8):
            continue
        adjusted = dict(row)
        for market in MARKETS:
            for side in ("own_", "opponent_"):
                field = side + market
                if adjusted.get(field) is not None:
                    adjusted[field] *= scale
        aligned.append(adjusted)
    return aligned


def _sample_quality(rows: list[dict], field: str, now: datetime) -> dict:
    observed = [row for row in rows if _count(row.get(field)) is not None]
    if not observed:
        return {"effective_samples": 0.0, "last_stat_match": None, "stat_age_days": None}
    weights = [
        0.5 ** (max(0, (now - row["scheduled_at"]).total_seconds()) / (120 * 86400))
        for row in observed
    ]
    total = sum(weights)
    effective = total * total / sum(w * w for w in weights)
    last = max(row["scheduled_at"] for row in observed)
    return {
        "effective_samples": round(effective, 2),
        "last_stat_match": last.isoformat(),
        "stat_age_days": max(0, (now.date() - last.date()).days),
    }


def project_market_state(state: Mapping | None, *, left_key: str, right_key: str,
                         tour: str, surface: str, best_of: int, now: datetime,
                         cutoff: datetime) -> dict:
    """Produce estimates only from observed, PIT-safe, tour-scoped evidence."""
    unavailable = {"aces": None, "double_faults": None}
    if not isinstance(state, Mapping) or state.get("schema") not in (1, 2):
        return unavailable
    if now.tzinfo is None or cutoff.tzinfo is None:
        return unavailable
    if str(state.get("cutoff_utc")) != cutoff.isoformat():
        return unavailable
    if str(state.get("provider_requests")) != "0":
        return unavailable
    if tour not in ("atp", "wta") or best_of not in (3, 5):
        return unavailable
    if not left_key.startswith(tour + ":") or not right_key.startswith(tour + ":"):
        return unavailable
    players = state.get("players")
    baselines = state.get("baselines")
    # Older already-published schema-1 snapshots still have authentic
    # pre-cutoff per-match stats. Serve same-format estimates until the
    # checksum-verified schema-2 release is ready; never fake BO3->BO5.
    legacy = state.get("schema") == 1
    lengths = {} if legacy else state.get("format_lengths")
    formatted = {} if legacy else state.get("format_baselines")
    if not all(isinstance(value, Mapping) for value in (players, baselines, lengths, formatted)):
        return unavailable
    tour_base = baselines.get(tour)
    if not isinstance(tour_base, Mapping):
        return unavailable

    histories = {}
    for key in (left_key, right_key):
        value = players.get(key)
        if not isinstance(value, Mapping) or not isinstance(value.get("samples"), list):
            return unavailable
        parsed = []
        for row in value["samples"]:
            if not isinstance(row, Mapping):
                return unavailable
            try:
                moment = datetime.fromisoformat(str(row["scheduled_at"]).replace("Z", "+00:00"))
                if moment.tzinfo is None or not moment < cutoff:
                    return unavailable
            except (KeyError, ValueError, TypeError):
                return unavailable
            validated = dict(row)
            for market in MARKETS:
                for side in ("own_", "opponent_"):
                    field = side + market
                    if validated.get(field) is not None:
                        if _count(validated[field]) is None:
                            return unavailable
                        validated[field] = float(validated[field])
            validated["scheduled_at"] = moment.astimezone(timezone.utc)
            parsed.append(validated)
        histories[key] = _aligned_samples(parsed, tour, surface, best_of, lengths)

    result = {}
    for market in MARKETS:
        baseline = _count(((formatted.get(tour) or {}).get(str(best_of)) or {}).get(market))
        if baseline is None:
            if best_of == 3:
                # Same-format tour fallback is valid when a BO3-specific
                # aggregate has too few samples.
                baseline = _count(tour_base.get(market))
            else:
                # Never transfer an unscaled all-format tour mean into BO5.
                # Cross-format fallback is allowed only when both observed
                # game-length aggregates and BO3 counts support calibration.
                source3 = _count(((formatted.get(tour) or {}).get("3") or {}).get(market))
                target_games = _length_mean(lengths, tour, surface, 5)
                source_games = _length_mean(lengths, tour, surface, 3)
                if source3 is not None and target_games and source_games:
                    baseline = source3 * target_games / source_games
        if baseline is None:
            result[market] = None
            continue
        a = _projection(left_key, right_key, market, histories, baseline,
                        now, surface=stats_surface_key(surface), best_of=best_of)
        b = _projection(right_key, left_key, market, histories, baseline,
                        now, surface=stats_surface_key(surface), best_of=best_of)

        def summary(item, key):
            if item is None:
                return None
            quality = _sample_quality(histories[key], "own_" + market, now)
            if (quality["effective_samples"] < MIN_EFFECTIVE_SAMPLES
                    or quality["stat_age_days"] is None
                    or quality["stat_age_days"] > MAX_STAT_AGE_DAYS):
                return None
            estimate = float(item["estimate"])
            sd = math.sqrt(max(1.44, float(item["variance"]),
                               estimate * (0.9 if market == "aces" else 1.1)))
            band = ("high" if quality["effective_samples"] >= 12
                    and quality["stat_age_days"] <= 60 and item["surface_samples"] >= 5
                    else "medium" if quality["effective_samples"] >= 6
                    and quality["stat_age_days"] <= 180 else "low")
            return {
                "estimate": round(estimate, 2),
                "samples": int(item["samples"]),
                "effective_samples": quality["effective_samples"],
                "last_stat_match": quality["last_stat_match"],
                "stat_age_days": quality["stat_age_days"],
                "quality_band": band,
                "surface_samples": int(item["surface_samples"]),
                "format_samples": int(item["best_of_samples"]),
                "opponent_samples": int(item["opponent_allowance_samples"]),
                "predictive_sd": round(sd, 2),
                # Gaussian heuristic, NOT an empirically calibrated coverage claim.
                "illustrative_range": [round(max(0.0, estimate - 1.28 * sd), 1),
                                       round(estimate + 1.28 * sd, 1)],
            }
        left = summary(a, left_key)
        right = summary(b, right_key)
        result[market] = {
            "player1": left,
            "player2": right,
            "total_estimate": round(left["estimate"] + right["estimate"], 2)
                if left is not None and right is not None else None,
            "method": ("canonical_legacy_same_format_decay_shrunk_opponent"
                       if legacy else "canonical_game_adjusted_when_verified_decay_shrunk_opponent"),
            "format_adjustment": "legacy_same_format_only" if legacy else "observed_total_games_only",
            "range_calibration": "heuristic_not_backtested",
            "not_betting_odds": True,
            "cutoff_utc": cutoff.isoformat(),
            "data_quality": "available" if left is not None and right is not None else "partial",
        }
    return result
