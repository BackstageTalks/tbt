from __future__ import annotations

import math
from typing import Any


# The untouched 2026 validation did not confirm that the former composite
# Prime Score improved Top-N selection over calibrated model probability.
# Production ranking therefore uses calibrated winner probability directly.
PRIME_RANKING_BASIS = "calibrated_model_probability"

# These labels are presentation defaults only. They are NOT claims about
# historical hit-rate guarantees. The web can override its display thresholds
# from ui-config.json after the full Prime segment audit is reviewed.
DEFAULT_PRIME_PROBABILITY_PCT = 80.0
DEFAULT_TOP_PRIME_PROBABILITY_PCT = 90.0

# Scales mirror the magnitude thresholds already used by predictor._signals.
_DIRECTIONAL_FACTORS = (
    ("Overall Strength", "elo_diff", 0.12),
    ("Surface Strength", "surface_elo_diff", 0.12),
    ("Official Ranking", "rank_advantage", 0.45),
    ("Recent Form", "recent_form_diff", 0.08),
    ("Opponent-adjusted Form", "opponent_adjusted_form_diff", 0.05),
    ("Surface Form", "surface_form_diff", 0.08),
    ("Head-to-Head", "h2h_advantage", 0.15),
)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _number(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _orientation(row: dict[str, Any]) -> float:
    """Return +1 when the prediction selects player1, -1 for player2."""
    p1_id = str(row.get("player1_id") or "")
    p2_id = str(row.get("player2_id") or "")
    winner_id = str(row.get("predicted_winner_id") or "")
    if winner_id and winner_id == p1_id:
        return 1.0
    if winner_id and winner_id == p2_id:
        return -1.0

    p1 = _number(row.get("player1_probability"), 0.5)
    p2 = _number(row.get("player2_probability"), 1.0 - p1)
    return 1.0 if p1 >= p2 else -1.0


def _winner_probability(row: dict[str, Any]) -> float:
    p1 = _clamp(_number(row.get("player1_probability"), 0.5), 0.0, 1.0)
    p2 = _clamp(_number(row.get("player2_probability"), 1.0 - p1), 0.0, 1.0)
    return max(p1, p2)


def _support_score(value: float, scale: float, orientation: float) -> float:
    """Normalize a directional feature to 0..100 from the predicted winner's view.

    50 is neutral, >50 supports the pick and <50 supports the opponent.
    This is an explanatory transform, not a probability and not the Prime ranking.
    """
    if scale <= 0:
        return 50.0
    normalized = math.tanh((orientation * value) / scale)
    return _clamp(50.0 + 45.0 * normalized, 5.0, 95.0)


def _feature_dict(row: dict[str, Any]) -> dict[str, Any]:
    features = row.get("features")
    return features if isinstance(features, dict) else {}


def _workload_value(features: dict[str, Any]) -> float:
    return (
        _number(features.get("rest_advantage"))
        + 0.25 * _number(features.get("layoff_advantage"))
        + 0.75 * _number(features.get("fatigue_3d_advantage"))
        + 0.40 * _number(features.get("fatigue_7d_advantage"))
    )


def _factor_rows(row: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    features = _feature_dict(row)
    orientation = _orientation(row)

    raw_scores: dict[str, float] = {}
    support_values: list[float] = []

    for label, name, scale in _DIRECTIONAL_FACTORS:
        score = _support_score(_number(features.get(name)), scale, orientation)
        raw_scores[label] = score
        support_values.append(score)

    workload_score = _support_score(_workload_value(features), 0.35, orientation)
    support_values.append(workload_score)

    recent_score = (
        raw_scores["Recent Form"] * 0.65
        + raw_scores["Opponent-adjusted Form"] * 0.35
    )
    surface_score = (
        raw_scores["Surface Strength"] * 0.72
        + raw_scores["Surface Form"] * 0.28
    )

    depth = _clamp(_number(features.get("data_depth"), 0.0), 0.0, 1.0) * 100.0

    display = [
        {"label": "Overall Strength", "score": round(raw_scores["Overall Strength"], 1), "kind": "advantage"},
        {"label": "Surface Strength", "score": round(surface_score, 1), "kind": "advantage"},
        {"label": "Recent Form", "score": round(recent_score, 1), "kind": "advantage"},
        {"label": "Head-to-Head", "score": round(raw_scores["Head-to-Head"], 1), "kind": "advantage"},
        {"label": "Rest / Workload", "score": round(workload_score, 1), "kind": "advantage"},
        {"label": "Data Depth", "score": round(depth, 1), "kind": "depth"},
    ]

    factor_agreement = sum(support_values) / len(support_values) if support_values else 50.0
    return display, factor_agreement


def prime_diagnostics(row: dict[str, Any]) -> dict[str, Any]:
    """Return transparent Prime context without inventing a second probability.

    Prime ranking is the calibrated winner probability. Data depth and factor
    agreement remain available as diagnostics/explanation and deterministic
    tie-breakers only.
    """
    winner_probability = _winner_probability(row)
    winner_probability_pct = winner_probability * 100.0

    features = _feature_dict(row)
    data_depth_pct = (
        _clamp(_number(features.get("data_depth"), 0.0), 0.0, 1.0)
        * 100.0
    )
    factors, factor_agreement_pct = _factor_rows(row)

    if winner_probability_pct >= DEFAULT_TOP_PRIME_PROBABILITY_PCT:
        level = "top_prime"
    elif winner_probability_pct >= DEFAULT_PRIME_PROBABILITY_PCT:
        level = "prime"
    else:
        level = "candidate"

    return {
        "ranking_basis": PRIME_RANKING_BASIS,
        "ranking_value_pct": round(winner_probability_pct, 2),
        "level": level,
        "winner_probability_pct": round(winner_probability_pct, 2),
        "data_depth_pct": round(data_depth_pct, 1),
        "factor_agreement_pct": round(factor_agreement_pct, 1),
        "factors": factors,
        "tie_breakers": ["factor_agreement_pct", "data_depth_pct"],
        "technical_note": (
            "BlinQ Prime Picks are ranked by calibrated model win probability. "
            "Data Depth and Factor Agreement are explanatory quality indicators "
            "and deterministic tie-breakers; they do not create a second win probability."
        ),
    }


def prime_predictions(
    rows: list[dict[str, Any]],
    *,
    limit: int = 10,
    minimum_probability_pct: float | None = None,
) -> list[dict[str, Any]]:
    ranked: list[tuple[float, float, float, dict[str, Any]]] = []

    for row in rows:
        prime = prime_diagnostics(row)
        probability_pct = float(prime["winner_probability_pct"])
        if (
            minimum_probability_pct is not None
            and probability_pct < float(minimum_probability_pct)
        ):
            continue

        copy = dict(row)
        copy["_prime"] = prime
        ranked.append(
            (
                probability_pct,
                float(prime["factor_agreement_pct"]),
                float(prime["data_depth_pct"]),
                copy,
            )
        )

    ranked.sort(
        key=lambda item: (
            -item[0],
            -item[1],
            -item[2],
            str(item[3].get("scheduled_at") or ""),
            str(item[3].get("match_id") or ""),
        )
    )
    return [item[3] for item in ranked[: max(1, min(int(limit), 50))]]
