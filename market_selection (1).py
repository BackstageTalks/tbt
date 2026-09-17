"""Point-in-time Aces / Double Faults projection shortlist.

This is deliberately a projection layer, not an odds model. TennisApi confirms
post-match Aces/DF counts in event statistics, but no dependable pre-match
Aces/DF price feed is assumed here. Cards therefore expose projected counts and
sample depth and must not be graded as odds-backed betting publications.
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
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _weighted_stats(samples: list[dict[str, Any]], field: str, now: datetime) -> tuple[float | None, float | None, int]:
    weighted: list[tuple[float, float]] = []
    for sample in samples:
        value = _number(sample.get(field))
        when = sample.get("scheduled_at")
        if value is None or not isinstance(when, datetime):
            continue
        days = max(0.0, (now - when).total_seconds() / 86400.0)
        weight = 0.5 ** (days / 120.0)
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


def _blend_special(
    base: float,
    samples: list[dict[str, Any]],
    field: str,
    now: datetime,
    *,
    surface: str,
    best_of: int | None,
) -> tuple[float, int, int]:
    surface_rows = [row for row in samples if surface and surface != "unknown" and row.get("surface") == surface]
    surface_mean, surface_n = _weighted_mean(surface_rows, field, now)
    if surface_mean is not None and surface_n >= 4:
        base = 0.75 * base + 0.25 * surface_mean

    best_rows = [row for row in samples if best_of and row.get("best_of") == best_of]
    best_mean, best_n = _weighted_mean(best_rows, field, now)
    if best_mean is not None and best_n >= 4:
        base = 0.82 * base + 0.18 * best_mean
    return base, surface_n, best_n


def _shrink(value: float, n: int, baseline: float, strength: float = 7.0) -> float:
    weight = n / (n + strength) if n > 0 else 0.0
    return weight * value + (1.0 - weight) * baseline


def _history_index(history, cutoff: datetime):
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    baselines = {"aces": [], "double_faults": []}
    stat_matches = {"aces": 0, "double_faults": 0}

    for match in history:
        if match.scheduled_at >= cutoff:
            continue
        status = str(match.status or "").strip().lower()
        if status in EXCLUDED_STATUSES:
            continue
        stats = match.stats if isinstance(match.stats, dict) else {}
        a1, a2 = _number(stats.get("p1_aces")), _number(stats.get("p2_aces"))
        d1, d2 = _number(stats.get("p1_double_faults")), _number(stats.get("p2_double_faults"))
        if a1 is not None or a2 is not None:
            stat_matches["aces"] += 1
        if d1 is not None or d2 is not None:
            stat_matches["double_faults"] += 1
        if a1 is not None:
            baselines["aces"].append(a1)
        if a2 is not None:
            baselines["aces"].append(a2)
        if d1 is not None:
            baselines["double_faults"].append(d1)
        if d2 is not None:
            baselines["double_faults"].append(d2)

        common = {
            "scheduled_at": match.scheduled_at.astimezone(timezone.utc),
            "surface": str(match.surface or "unknown").lower(),
            "best_of": match.best_of,
        }
        by_player[str(match.player1_id)].append({
            **common,
            "own_aces": a1, "opponent_aces": a2,
            "own_double_faults": d1, "opponent_double_faults": d2,
        })
        by_player[str(match.player2_id)].append({
            **common,
            "own_aces": a2, "opponent_aces": a1,
            "own_double_faults": d2, "opponent_double_faults": d1,
        })

    baseline = {}
    for market in ("aces", "double_faults"):
        values = baselines[market]
        # Conservative fallback is used only for shrinkage; it never creates a
        # publishable pick without actual player samples.
        fallback = 4.0 if market == "aces" else 2.5
        baseline[market] = sum(values) / len(values) if values else fallback
    return by_player, baseline, stat_matches


def _projection(
    player_id: str,
    opponent_id: str,
    market: str,
    histories: dict[str, list[dict[str, Any]]],
    baseline: float,
    now: datetime,
    *,
    surface: str,
    best_of: int | None,
) -> dict[str, Any] | None:
    own_rows = histories.get(str(player_id), [])
    opponent_rows = histories.get(str(opponent_id), [])
    own_field = f"own_{market}"
    allowance_field = f"opponent_{market}"

    own_mean, own_var, own_n = _weighted_stats(own_rows, own_field, now)
    if own_mean is None or own_n < 6:
        return None
    own_mean, surface_n, best_n = _blend_special(
        own_mean, own_rows, own_field, now, surface=surface, best_of=best_of
    )
    own_estimate = _shrink(own_mean, own_n, baseline)

    allowed_mean, allowed_var, allowed_n = _weighted_stats(opponent_rows, allowance_field, now)
    if allowed_mean is None:
        allowed_estimate = baseline
        allowed_var = None
        allowed_n = 0
    else:
        allowed_estimate = _shrink(allowed_mean, allowed_n, baseline)

    # Opponent influence is market-specific and itself reliability weighted.
    base_opponent_weight = 0.30 if market == "aces" else 0.10
    allowance_reliability = min(1.0, allowed_n / 12.0)
    opponent_weight = base_opponent_weight * allowance_reliability
    estimate = (1.0 - opponent_weight) * own_estimate + opponent_weight * allowed_estimate

    own_var = float(own_var or 0.0)
    allowed_var = float(allowed_var if allowed_var is not None else own_var)
    variance = ((1.0 - opponent_weight) ** 2) * own_var + (opponent_weight ** 2) * allowed_var
    return {
        "estimate": max(0.0, estimate),
        "variance": max(0.0, variance),
        "samples": own_n,
        "surface_samples": surface_n,
        "best_of_samples": best_n,
        "opponent_allowance_samples": allowed_n,
        "opponent_weight": opponent_weight,
    }


def _card(
    row: dict[str, Any],
    market: str,
    p1_projection: dict[str, Any],
    p2_projection: dict[str, Any],
) -> dict[str, Any] | None:
    p1 = row.get("player1") if isinstance(row.get("player1"), dict) else {}
    p2 = row.get("player2") if isinstance(row.get("player2"), dict) else {}
    e1, e2 = p1_projection["estimate"], p2_projection["estimate"]
    gap = abs(e1 - e2)
    min_gap = 0.85 if market == "aces" else 0.45
    if gap < min_gap:
        return None

    selected, other, selected_projection, opponent_projection = (
        (p1, p2, p1_projection, p2_projection) if e1 > e2
        else (p2, p1, p2_projection, p1_projection)
    )
    depth_n = min(int(p1_projection["samples"]), int(p2_projection["samples"]))
    depth = min(1.0, depth_n / 20.0)
    surface_depth = min(int(p1_projection["surface_samples"]), int(p2_projection["surface_samples"]))
    surface_factor = min(1.0, surface_depth / 8.0) if surface_depth else 0.0

    # Evidence-aware superiority confidence. Variance keeps noisy player histories
    # from receiving 90%+ confidence merely because their means are far apart.
    v1 = float(p1_projection.get("variance") or 0.0)
    v2 = float(p2_projection.get("variance") or 0.0)
    n1 = max(1, int(p1_projection["samples"]))
    n2 = max(1, int(p2_projection["samples"]))
    variance_floor = 1.0 if market == "aces" else 0.35
    standard_error = math.sqrt(max(variance_floor ** 2, v1 / n1 + v2 / n2))
    z = gap / standard_error if standard_error > 0 else 0.0
    raw_superiority = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    evidence = min(1.0, 0.85 * depth + 0.15 * surface_factor)
    confidence = 0.5 + (raw_superiority - 0.5) * evidence
    confidence = max(0.5, min(0.97, confidence))
    if confidence < 0.60:
        return None

    label = "Most Aces" if market == "aces" else "Most Double Faults"
    card = deepcopy(row)
    card.pop("market_publication_candidates", None)
    card.pop("betting", None)
    card.pop("match_winner_market", None)
    card.update({
        "market": market,
        "market_type": label,
        "pick": selected.get("name") or "—",
        "selection": selected.get("name") or "—",
        "selection_id": str(selected.get("id") or ""),
        "projection": round(float(selected_projection["estimate"]), 2),
        "opponent_projection": round(float(opponent_projection["estimate"]), 2),
        "projection_gap": round(float(gap), 2),
        "projection_confidence": round(float(confidence), 4),
        "raw_superiority_confidence": round(float(raw_superiority), 4),
        "projection_uncertainty": round(float(standard_error), 3),
        "probability": None,
        "odds": None,
        "edge": None,
        "expected_value": None,
        "price_status": "projection_only",
        "projection_model": "ace-count-projection-v2",
        "projection_source": "historical_event_statistics",
        "projection_samples": {
            "player1": int(p1_projection["samples"]),
            "player2": int(p2_projection["samples"]),
            "player1_surface": int(p1_projection["surface_samples"]),
            "player2_surface": int(p2_projection["surface_samples"]),
        },
        "data_depth": round(depth, 4),
        "projection_score": confidence * (1.0 + min(2.0, gap / (2.5 if market == "aces" else 1.25))),
    })
    return card



def _adaptive_confidence_select(
    cards: list[dict[str, Any]],
    *,
    target_count: int = 10,
    start_probability: float = 0.80,
    minimum_probability: float = 0.48,
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

def select_ace_picks(
    history,
    predictions: list[dict[str, Any]],
    *,
    now: datetime,
    per_market_limit: int = 10,
    total_limit: int = 20,
    target_count: int = 10,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return a small, point-in-time projection shortlist from stored counts."""
    if now.tzinfo is None:
        raise ValueError("select_ace_picks requires timezone-aware now")
    now = now.astimezone(timezone.utc)
    # Match completion timestamps are unavailable, so mirror the conservative
    # Match Winner policy: no same-UTC-day post-match statistics are consumed.
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    histories, baselines, stat_matches = _history_index(history, cutoff)

    by_market: dict[str, list[dict[str, Any]]] = {"aces": [], "double_faults": []}
    eligible_matches = 0
    for row in predictions:
        p1 = row.get("player1") if isinstance(row.get("player1"), dict) else {}
        p2 = row.get("player2") if isinstance(row.get("player2"), dict) else {}
        p1_id, p2_id = str(p1.get("id") or ""), str(p2.get("id") or "")
        if not p1_id or not p2_id:
            continue
        eligible_matches += 1
        surface = str(row.get("surface") or "unknown").lower()
        best_of = row.get("best_of")
        try:
            best_of = int(best_of) if best_of is not None else None
        except (TypeError, ValueError):
            best_of = None

        for market in ("aces", "double_faults"):
            p1_projection = _projection(
                p1_id, p2_id, market, histories, baselines[market], now,
                surface=surface, best_of=best_of,
            )
            p2_projection = _projection(
                p2_id, p1_id, market, histories, baselines[market], now,
                surface=surface, best_of=best_of,
            )
            if p1_projection is None or p2_projection is None:
                continue
            card = _card(row, market, p1_projection, p2_projection)
            if card is not None:
                by_market[market].append(card)

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

    candidates = by_market["aces"] + by_market["double_faults"]
    candidates.sort(key=lambda row: float(row.get("projection_score") or 0.0), reverse=True)
    combined, applied_floor, tier_counts = _adaptive_confidence_select(
        candidates, target_count=target_count, minimum_probability=0.60
    )
    combined = combined[: max(0, int(total_limit))]
    for row in combined:
        row.pop("projection_score", None)

    return combined, {
        "schema": 3,
        "model": "ace-count-projection-v2",
        "cutoff_utc": cutoff.isoformat(),
        "projection_only": True,
        "odds_backed": False,
        "settlement_enabled": False,
        "eligible_upcoming_matches": eligible_matches,
        "history_matches_with_aces": stat_matches["aces"],
        "history_matches_with_double_faults": stat_matches["double_faults"],
        "baseline_aces": round(baselines["aces"], 3),
        "baseline_double_faults": round(baselines["double_faults"], 3),
        "aces_selected": sum(row.get("market") == "aces" for row in combined),
        "double_faults_selected": sum(row.get("market") == "double_faults" for row in combined),
        "selected": len(combined),
        "per_market_limit": int(per_market_limit),
        "total_limit": int(total_limit),
        "target_count": int(target_count),
        "adaptive_confidence_floor": None if applied_floor is None else float(applied_floor),
        "adaptive_tier_counts": tier_counts,
        "fill_policy": "evidence_adjusted_confidence_hard_floor_0.60",
    }
