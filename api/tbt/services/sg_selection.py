"""Point-in-time Sets / Games projection shortlist.

The layer uses only structured historical set/game scores recorded before the
current UTC day. It is intentionally projection-only until BlinQ validates and
backtests a dependable pre-match Sets/Games price/line mapping.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import math
from typing import Any


EXCLUDED_STATUSES = {
    "retired", "walkover", "walk over", "cancelled", "canceled",
    "abandoned", "interrupted", "suspended", "postponed",
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _weighted_mean(samples: list[dict[str, Any]], field: str, now: datetime) -> tuple[float | None, int]:
    numerator = denominator = 0.0
    count = 0
    for sample in samples:
        value = _number(sample.get(field))
        when = sample.get("scheduled_at")
        if value is None or not isinstance(when, datetime):
            continue
        days = max(0.0, (now - when).total_seconds() / 86400.0)
        weight = 0.5 ** (days / 150.0)
        numerator += value * weight
        denominator += weight
        count += 1
    return ((numerator / denominator) if denominator > 0 else None), count


def _shrink(value: float, n: int, baseline: float, strength: float = 8.0) -> float:
    weight = n / (n + strength) if n > 0 else 0.0
    return weight * value + (1.0 - weight) * baseline


def _long_match(total_sets: float, best_of: int) -> float:
    if best_of == 3:
        return float(total_sets >= 3)
    if best_of == 5:
        return float(total_sets >= 4)
    return 0.0


def _history_index(history, cutoff: datetime):
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    baselines: dict[tuple[str, int], dict[str, list[float]]] = defaultdict(
        lambda: {"games": [], "long": []}
    )
    score_matches = 0

    for match in history:
        if match.scheduled_at >= cutoff:
            continue
        if str(match.status or "").strip().lower() in EXCLUDED_STATUSES:
            continue
        try:
            best_of = int(match.best_of) if match.best_of is not None else None
        except (TypeError, ValueError):
            best_of = None
        if best_of not in {3, 5}:
            continue
        stats = match.stats if isinstance(match.stats, dict) else {}
        total_sets = _number(stats.get("total_sets"))
        total_games = _number(stats.get("total_games"))
        if total_sets is None or total_games is None:
            continue
        if total_sets < 2 or total_games < 12:
            continue
        long_value = _long_match(total_sets, best_of)
        key = (str(match.tour or "").lower(), best_of)
        baselines[key]["games"].append(total_games)
        baselines[key]["long"].append(long_value)
        score_matches += 1
        common = {
            "scheduled_at": match.scheduled_at.astimezone(timezone.utc),
            "surface": str(match.surface or "unknown").lower(),
            "best_of": best_of,
            "tour": str(match.tour or "").lower(),
            "total_games": total_games,
            "long_match": long_value,
        }
        by_player[str(match.player1_id)].append(common)
        by_player[str(match.player2_id)].append(common)

    baseline_values: dict[tuple[str, int], dict[str, float]] = {}
    for key, values in baselines.items():
        games = values["games"]
        long = values["long"]
        if games and long:
            baseline_values[key] = {
                "games": sum(games) / len(games),
                "long": sum(long) / len(long),
                "n": float(len(games)),
            }
    return by_player, baseline_values, score_matches


def _player_estimate(
    player_id: str,
    histories: dict[str, list[dict[str, Any]]],
    field: str,
    now: datetime,
    *,
    tour: str,
    surface: str,
    best_of: int,
    baseline: float,
) -> dict[str, Any] | None:
    rows = [
        row for row in histories.get(str(player_id), [])
        if row.get("best_of") == best_of and row.get("tour") == tour
    ]
    mean, n = _weighted_mean(rows, field, now)
    if mean is None or n < 6:
        return None
    estimate = _shrink(mean, n, baseline)
    surface_rows = [
        row for row in rows
        if surface and surface != "unknown" and row.get("surface") == surface
    ]
    surface_mean, surface_n = _weighted_mean(surface_rows, field, now)
    if surface_mean is not None and surface_n >= 4:
        estimate = 0.75 * estimate + 0.25 * _shrink(surface_mean, surface_n, baseline, strength=5.0)
    return {
        "estimate": estimate,
        "samples": n,
        "surface_samples": surface_n,
    }


def _sets_card(
    row: dict[str, Any],
    p1: dict[str, Any],
    p2: dict[str, Any],
    *,
    best_of: int,
    baseline: float,
) -> dict[str, Any] | None:
    probability = (p1["estimate"] + p2["estimate"]) / 2.0
    probability = max(0.02, min(0.98, probability))
    distance = abs(probability - 0.5)
    if distance < 0.10:
        return None
    is_over = probability > 0.5
    selected_probability = probability if is_over else 1.0 - probability
    depth_n = min(int(p1["samples"]), int(p2["samples"]))
    depth = min(1.0, depth_n / 24.0)
    confidence = min(0.95, 0.30 + 0.45 * depth + 0.25 * min(1.0, distance / 0.22))
    if confidence < 0.52 or selected_probability < 0.60:
        return None

    line = 2.5 if best_of == 3 else 3.5
    selection = f"{'Over' if is_over else 'Under'} {line:.1f} Sets"
    card = deepcopy(row)
    card.pop("market_publication_candidates", None)
    card.pop("betting", None)
    card.pop("match_winner_market", None)
    card.update({
        "market": "sets",
        "market_type": "Total Sets Projection",
        "pick": selection,
        "selection": selection,
        "selection_id": f"sets:{'over' if is_over else 'under'}:{line:.1f}",
        "projection": round(selected_probability, 4),
        "projection_unit": "probability",
        "raw_long_match_probability": round(probability, 4),
        "reference_projection": 0.5,
        "projection_gap": round(distance, 4),
        "projection_confidence": round(confidence, 4),
        "probability": None,
        "odds": None,
        "edge": None,
        "expected_value": None,
        "price_status": "projection_only",
        "projection_model": "sets-games-projection-v1",
        "projection_source": "historical_structured_scores",
        "projection_samples": {
            "player1": int(p1["samples"]),
            "player2": int(p2["samples"]),
            "player1_surface": int(p1["surface_samples"]),
            "player2_surface": int(p2["surface_samples"]),
        },
        "baseline_projection": round(float(baseline), 4),
        "best_of": best_of,
        "data_depth": depth,
        "projection_score": confidence * (1.0 + distance * 3.0),
    })
    return card


def _games_card(
    row: dict[str, Any],
    p1: dict[str, Any],
    p2: dict[str, Any],
    *,
    best_of: int,
    baseline: float,
) -> dict[str, Any] | None:
    estimate = (p1["estimate"] + p2["estimate"]) / 2.0
    deviation = estimate - baseline
    min_deviation = 1.4 if best_of == 3 else 2.2
    if abs(deviation) < min_deviation:
        return None
    direction = "High" if deviation > 0 else "Low"
    selection = f"{direction} Total Games"
    depth_n = min(int(p1["samples"]), int(p2["samples"]))
    depth = min(1.0, depth_n / 24.0)
    scale = 4.0 if best_of == 3 else 6.0
    signal = min(1.0, abs(deviation) / scale)
    confidence = min(0.95, 0.30 + 0.45 * depth + 0.25 * signal)
    if confidence < 0.52:
        return None

    card = deepcopy(row)
    card.pop("market_publication_candidates", None)
    card.pop("betting", None)
    card.pop("match_winner_market", None)
    card.update({
        "market": "games",
        "market_type": "Total Games Projection",
        "pick": selection,
        "selection": selection,
        "selection_id": f"games:{direction.lower()}",
        "projection": round(float(estimate), 2),
        "projection_unit": "games",
        "reference_projection": round(float(baseline), 2),
        "projection_gap": round(abs(float(deviation)), 2),
        "projection_direction": direction.lower(),
        "projection_confidence": round(confidence, 4),
        "probability": None,
        "odds": None,
        "edge": None,
        "expected_value": None,
        "price_status": "projection_only",
        "projection_model": "sets-games-projection-v1",
        "projection_source": "historical_structured_scores",
        "projection_samples": {
            "player1": int(p1["samples"]),
            "player2": int(p2["samples"]),
            "player1_surface": int(p1["surface_samples"]),
            "player2_surface": int(p2["surface_samples"]),
        },
        "baseline_projection": round(float(baseline), 2),
        "best_of": best_of,
        "data_depth": depth,
        "projection_score": confidence * (1.0 + abs(deviation) / scale),
    })
    return card


def select_sg_picks(
    history,
    predictions: list[dict[str, Any]],
    *,
    now: datetime,
    per_market_limit: int = 5,
    total_limit: int = 10,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if now.tzinfo is None:
        raise ValueError("select_sg_picks requires timezone-aware now")
    now = now.astimezone(timezone.utc)
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    histories, baselines, score_matches = _history_index(history, cutoff)

    by_market: dict[str, list[dict[str, Any]]] = {"sets": [], "games": []}
    eligible = 0
    missing_best_of = 0
    missing_baseline = 0
    for row in predictions:
        p1_obj = row.get("player1") if isinstance(row.get("player1"), dict) else {}
        p2_obj = row.get("player2") if isinstance(row.get("player2"), dict) else {}
        p1_id, p2_id = str(p1_obj.get("id") or ""), str(p2_obj.get("id") or "")
        if not p1_id or not p2_id:
            continue
        try:
            best_of = int(row.get("best_of"))
        except (TypeError, ValueError):
            missing_best_of += 1
            continue
        if best_of not in {3, 5}:
            missing_best_of += 1
            continue
        tour = str(row.get("tour") or "").lower()
        surface = str(row.get("surface") or "unknown").lower()
        baseline = baselines.get((tour, best_of))
        if not baseline:
            missing_baseline += 1
            continue
        eligible += 1

        p1_sets = _player_estimate(
            p1_id, histories, "long_match", now,
            tour=tour, surface=surface, best_of=best_of,
            baseline=float(baseline["long"]),
        )
        p2_sets = _player_estimate(
            p2_id, histories, "long_match", now,
            tour=tour, surface=surface, best_of=best_of,
            baseline=float(baseline["long"]),
        )
        if p1_sets and p2_sets:
            card = _sets_card(
                row, p1_sets, p2_sets, best_of=best_of,
                baseline=float(baseline["long"]),
            )
            if card:
                by_market["sets"].append(card)

        p1_games = _player_estimate(
            p1_id, histories, "total_games", now,
            tour=tour, surface=surface, best_of=best_of,
            baseline=float(baseline["games"]),
        )
        p2_games = _player_estimate(
            p2_id, histories, "total_games", now,
            tour=tour, surface=surface, best_of=best_of,
            baseline=float(baseline["games"]),
        )
        if p1_games and p2_games:
            card = _games_card(
                row, p1_games, p2_games, best_of=best_of,
                baseline=float(baseline["games"]),
            )
            if card:
                by_market["games"].append(card)

    for market in by_market:
        by_market[market].sort(
            key=lambda row: (
                float(row.get("projection_score") or 0.0),
                float(row.get("projection_confidence") or 0.0),
                float(row.get("projection_gap") or 0.0),
            ),
            reverse=True,
        )
        by_market[market] = by_market[market][: max(0, int(per_market_limit))]

    combined = by_market["sets"] + by_market["games"]
    combined.sort(key=lambda row: float(row.get("projection_score") or 0.0), reverse=True)
    combined = combined[: max(0, int(total_limit))]
    for row in combined:
        row.pop("projection_score", None)

    baseline_report = {
        f"{tour}_bo{best_of}": {
            "games": round(float(values["games"]), 3),
            "long_match_probability": round(float(values["long"]), 4),
            "n": int(values["n"]),
        }
        for (tour, best_of), values in sorted(baselines.items())
    }
    return combined, {
        "schema": 1,
        "model": "sets-games-projection-v1",
        "cutoff_utc": cutoff.isoformat(),
        "projection_only": True,
        "odds_backed": False,
        "settlement_enabled": False,
        "history_matches_with_structured_score": score_matches,
        "eligible_upcoming_matches": eligible,
        "missing_best_of": missing_best_of,
        "missing_baseline": missing_baseline,
        "sets_selected": sum(row.get("market") == "sets" for row in combined),
        "games_selected": sum(row.get("market") == "games" for row in combined),
        "selected": len(combined),
        "per_market_limit": int(per_market_limit),
        "total_limit": int(total_limit),
        "baselines": baseline_report,
    }
