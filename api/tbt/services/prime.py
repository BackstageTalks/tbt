from __future__ import annotations

import math
from typing import Any


# Provisional production weights only. The Prime backtest searches candidate
# weights on an earlier out-of-time year and validates the chosen combination
# on a later untouched year before these should be considered final.
DEFAULT_PRIME_WEIGHTS = {
    "model_probability": 0.70,
    "data_depth": 0.20,
    "factor_agreement": 0.10,
}

# Same feature magnitudes used by predictor._signals. These are not odds and
# are not treated as probabilities; they only normalize directional support.
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
    """+1 if the predicted winner is player1, -1 if player2."""
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


def _support_score(value: float, scale: float, orientation: float) -> float:
    """Directional display score in 0..100; 50 is neutral.

    This transform is deliberately not described as probability.
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

    agreement_pct = sum(support_values) / len(support_values) if support_values else 50.0
    return display, agreement_pct


def prime_components(row: dict[str, Any]) -> dict[str, Any]:
    """Return normalized 0..1 ranking components plus display diagnostics.

    model_probability_strength:
      50% => 0, 100% => 1. This keeps a coin-flip prediction from receiving
      half of the Prime score merely because probabilities start at 0.5.

    factor_agreement_strength:
      neutral directional support (50/100) => 0; very strong agreement => 1.
      Opposition to the selected player is clamped to 0 for ranking purposes.
    """
    p1 = _clamp(_number(row.get("player1_probability"), 0.5), 0.0, 1.0)
    p2 = _clamp(_number(row.get("player2_probability"), 1.0 - p1), 0.0, 1.0)
    winner_probability = max(p1, p2)

    features = _feature_dict(row)
    data_depth = _clamp(_number(features.get("data_depth"), 0.0), 0.0, 1.0)
    factors, agreement_pct = _factor_rows(row)

    model_probability_strength = _clamp((winner_probability - 0.5) / 0.5, 0.0, 1.0)
    factor_agreement_strength = _clamp((agreement_pct - 50.0) / 45.0, 0.0, 1.0)

    return {
        "winner_probability": winner_probability,
        "winner_probability_pct": winner_probability * 100.0,
        "model_probability_strength": model_probability_strength,
        "data_depth": data_depth,
        "data_depth_pct": data_depth * 100.0,
        "factor_agreement_pct": agreement_pct,
        "factor_agreement_strength": factor_agreement_strength,
        "factors": factors,
    }


def _normalized_weights(weights: dict[str, float] | None) -> dict[str, float]:
    source = dict(weights or DEFAULT_PRIME_WEIGHTS)
    cleaned = {
        "model_probability": max(0.0, _number(source.get("model_probability"))),
        "data_depth": max(0.0, _number(source.get("data_depth"))),
        "factor_agreement": max(0.0, _number(source.get("factor_agreement"))),
    }
    total = sum(cleaned.values())
    if total <= 0:
        return dict(DEFAULT_PRIME_WEIGHTS)
    return {key: value / total for key, value in cleaned.items()}


def prime_score_from_components(
    components: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> float:
    w = _normalized_weights(weights)
    score = 100.0 * (
        w["model_probability"] * _number(components.get("model_probability_strength"))
        + w["data_depth"] * _number(components.get("data_depth"))
        + w["factor_agreement"] * _number(components.get("factor_agreement_strength"))
    )
    return _clamp(score, 0.0, 100.0)


def prime_diagnostics(
    row: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    components = prime_components(row)
    normalized = _normalized_weights(weights)
    score = prime_score_from_components(components, normalized)

    winner_probability = float(components["winner_probability"])
    data_depth = float(components["data_depth"])
    if score >= 75.0 and winner_probability >= 0.76 and data_depth >= 0.45:
        level = "top_prime"
    elif winner_probability >= 0.63 and data_depth >= 0.20:
        level = "prime"
    else:
        level = "candidate"

    return {
        "score": round(score, 2),
        "level": level,
        "winner_probability_pct": round(float(components["winner_probability_pct"]), 2),
        "data_depth_pct": round(float(components["data_depth_pct"]), 1),
        "factor_agreement_pct": round(float(components["factor_agreement_pct"]), 1),
        "components": {
            "model_probability_strength": round(float(components["model_probability_strength"]), 6),
            "data_depth": round(data_depth, 6),
            "factor_agreement_strength": round(float(components["factor_agreement_strength"]), 6),
        },
        "factors": components["factors"],
        "weights": normalized,
        "technical_note": (
            "Prime Score is a ranking score, not a second win probability and not a bookmaker edge. "
            "Its final production weights should be selected by out-of-time Prime backtesting."
        ),
    }


def prime_predictions(
    rows: list[dict[str, Any]],
    *,
    limit: int = 10,
    minimum_score: float | None = None,
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    ranked: list[tuple[float, float, dict[str, Any]]] = []
    for row in rows:
        prime = prime_diagnostics(row, weights=weights)
        score = float(prime["score"])
        if minimum_score is not None and score < minimum_score:
            continue
        probability = max(
            _number(row.get("player1_probability"), 0.5),
            _number(row.get("player2_probability"), 0.5),
        )
        copy = dict(row)
        copy["_prime"] = prime
        ranked.append((score, probability, copy))

    ranked.sort(key=lambda item: (-item[0], -item[1], str(item[2].get("scheduled_at") or "")))
    chosen = [item[2] for item in ranked[: max(1, min(int(limit), 50))]]
    for index, row in enumerate(chosen, start=1):
        row["_prime"]["rank"] = index
    return chosen
