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


def _weighted_stats(samples: list[dict[str, Any]], field: str, now: datetime) -> tuple[float | None, float | None, int]:
    weighted: list[tuple[float, float]] = []
    for sample in samples:
        value = _number(sample.get(field))
        when = sample.get("scheduled_at")
        if value is None or not isinstance(when, datetime):
            continue
        days = max(0.0, (now - when).total_seconds() / 86400.0)
        weight = 0.5 ** (days / 150.0)
        weighted.append((value, weight))
    if not weighted:
        return None, None, 0
    total_w = sum(w for _, w in weighted)
    mean = sum(v * w for v, w in weighted) / total_w
    variance = sum(w * (v - mean) ** 2 for v, w in weighted) / total_w if len(weighted) > 1 else 0.0
    return mean, max(0.0, variance), len(weighted)


def _weighted_mean(samples: list[dict[str, Any]], field: str, now: datetime) -> tuple[float | None, int]:
    mean, _, count = _weighted_stats(samples, field, now)
    return mean, count


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
    rows = [row for row in histories.get(str(player_id), []) if row.get("best_of") == best_of and row.get("tour") == tour]
    mean, variance, n = _weighted_stats(rows, field, now)
    if mean is None or n < 6:
        return None
    estimate = _shrink(mean, n, baseline)
    surface_rows = [row for row in rows if surface and surface != "unknown" and row.get("surface") == surface]
    surface_mean, surface_variance, surface_n = _weighted_stats(surface_rows, field, now)
    if surface_mean is not None and surface_n >= 4:
        surface_est = _shrink(surface_mean, surface_n, baseline, strength=5.0)
        estimate = 0.75 * estimate + 0.25 * surface_est
        if surface_variance is not None:
            variance = 0.75 * float(variance or 0.0) + 0.25 * float(surface_variance)
    return {
        "estimate": estimate,
        "variance": max(0.0, float(variance or 0.0)),
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
    raw_probability = max(0.02, min(0.98, (p1["estimate"] + p2["estimate"]) / 2.0))
    depth_n = min(int(p1["samples"]), int(p2["samples"]))
    depth = min(1.0, depth_n / 24.0)
    surface_depth = min(int(p1["surface_samples"]), int(p2["surface_samples"]))
    surface_factor = min(1.0, surface_depth / 8.0) if surface_depth else 0.0
    evidence = min(1.0, 0.85 * math.sqrt(depth) + 0.15 * surface_factor)

    # Shrink the historical long-match probability toward 50% when evidence is
    # incomplete; this prevents a sparse 90% estimate from being displayed as 90%.
    adjusted_probability = 0.5 + (raw_probability - 0.5) * evidence
    is_over = adjusted_probability > 0.5
    selected_probability = adjusted_probability if is_over else 1.0 - adjusted_probability
    distance = abs(adjusted_probability - 0.5)
    if selected_probability < 0.60:
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
        "raw_long_match_probability": round(raw_probability, 4),
        "evidence_adjusted_probability": round(adjusted_probability, 4),
        "reference_projection": 0.5,
        "projection_gap": round(distance, 4),
        "projection_confidence": round(selected_probability, 4),
        "probability": None,
        "odds": None,
        "edge": None,
        "expected_value": None,
        "price_status": "projection_only",
        "projection_model": "sets-games-projection-v2",
        "projection_source": "historical_structured_scores",
        "projection_samples": {
            "player1": int(p1["samples"]), "player2": int(p2["samples"]),
            "player1_surface": int(p1["surface_samples"]), "player2_surface": int(p2["surface_samples"]),
        },
        "baseline_projection": round(float(baseline), 4),
        "best_of": best_of,
        "data_depth": round(depth, 4),
        "projection_score": selected_probability * (1.0 + distance * 2.0),
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
    surface_depth = min(int(p1["surface_samples"]), int(p2["surface_samples"]))
    surface_factor = min(1.0, surface_depth / 8.0) if surface_depth else 0.0

    v1, v2 = float(p1.get("variance") or 0.0), float(p2.get("variance") or 0.0)
    n1, n2 = max(1, int(p1["samples"])), max(1, int(p2["samples"]))
    se = math.sqrt(max(1.5 ** 2, 0.25 * (v1 / n1 + v2 / n2)))
    z = abs(deviation) / se if se > 0 else 0.0
    raw_direction_probability = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    evidence = min(1.0, 0.85 * math.sqrt(depth) + 0.15 * surface_factor)
    confidence = 0.5 + (raw_direction_probability - 0.5) * evidence
    confidence = max(0.5, min(0.97, confidence))
    if confidence < 0.60:
        return None

    card = deepcopy(row)
    card.pop("market_publication_candidates", None)
    card.pop("betting", None)
    card.pop("match_winner_market", None)
    card.update({
        "market": "games", "market_type": "Total Games Projection",
        "pick": selection, "selection": selection, "selection_id": f"games:{direction.lower()}",
        "projection": round(float(estimate), 2), "projection_unit": "games",
        "reference_projection": round(float(baseline), 2),
        "projection_gap": round(abs(float(deviation)), 2),
        "projection_direction": direction.lower(),
        "projection_confidence": round(confidence, 4),
        "raw_direction_confidence": round(raw_direction_probability, 4),
        "projection_uncertainty": round(se, 3),
        "probability": None, "odds": None, "edge": None, "expected_value": None,
        "price_status": "projection_only",
        "projection_model": "sets-games-projection-v2",
        "projection_source": "historical_structured_scores",
        "projection_samples": {
            "player1": int(p1["samples"]), "player2": int(p2["samples"]),
            "player1_surface": int(p1["surface_samples"]), "player2_surface": int(p2["surface_samples"]),
        },
        "baseline_projection": round(float(baseline), 2),
        "best_of": best_of, "data_depth": round(depth, 4),
        "projection_score": confidence * (1.0 + min(2.0, abs(deviation) / (4.0 if best_of == 3 else 6.0))),
    })
    return card



def _adaptive_confidence_select(
    cards: list[dict[str, Any]],
    *,
    target_count: int = 10,
    start_probability: float = 0.80,
    minimum_probability: float = 0.52,
    step: float = 0.02,
) -> tuple[list[dict[str, Any]], float | None, dict[str, int]]:
    """Fill toward the daily target by relaxing confidence only.

    Data depth, sample-size, surface and signal/gap guards are applied before
    this helper and are never bypassed. If the hard floor still produces fewer
    than the target, the smaller honest set is returned.
    """
    minimum=max(0.0,min(1.0,float(minimum_probability)))
    threshold=max(minimum,min(1.0,float(start_probability)))
    thresholds=[]
    while threshold > minimum + 1e-9:
        thresholds.append(round(threshold, 4))
        threshold -= max(0.001,float(step))
    thresholds.append(round(minimum,4))
    thresholds=sorted(set(thresholds),reverse=True)
    selected=[];applied=None;counts={}
    for floor in thresholds:
        selected=[row for row in cards if float(row.get("projection_confidence") or 0.0) >= floor]
        counts[f"{floor:.2f}"]=len(selected)
        applied=floor
        if len(selected)>=max(1,int(target_count)):
            break
    return selected,applied,counts

def select_sg_picks(
    history,
    predictions: list[dict[str, Any]],
    *,
    now: datetime,
    per_market_limit: int = 10,
    total_limit: int = 20,
    target_count: int = 10,
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

    candidates = by_market["sets"] + by_market["games"]
    candidates.sort(key=lambda row: float(row.get("projection_score") or 0.0), reverse=True)
    combined, applied_floor, tier_counts = _adaptive_confidence_select(
        candidates, target_count=target_count, minimum_probability=0.60
    )
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
        "schema": 3,
        "model": "sets-games-projection-v2",
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
        "target_count": int(target_count),
        "adaptive_confidence_floor": None if applied_floor is None else float(applied_floor),
        "adaptive_tier_counts": tier_counts,
        "fill_policy": "evidence_adjusted_confidence_hard_floor_0.60",
        "baselines": baseline_report,
    }
