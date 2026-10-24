"""Validated inference composition for a future governed specialist bundle.

No fitting, weight selection or production registration happens here.
Weights must come from a preceding selection period, never serving outcomes.
"""
from __future__ import annotations

import numpy as np


def pooled_predictions(frame, pooled, specialists, weights):
    """Preserve row order and use the pooled model for absent specialists.

    Positional routing deliberately supports duplicate pandas index labels.
    Unknown tours are rejected: they must not silently become WTA.
    """
    allowed = {"atp", "wta"}
    if set(specialists) - allowed or set(weights) - allowed:
        raise ValueError("Unknown specialist tour")
    for tour, weight in weights.items():
        if isinstance(weight, bool) or not np.isfinite(weight) or not 0 <= weight <= 1:
            raise ValueError("Invalid specialist weight")
        if weight > 0 and tour not in specialists:
            raise ValueError("Positive weight requires a specialist")
    if "tour_atp" not in frame or not frame.tour_atp.isin([0, 1]).all():
        raise ValueError("Explicit ATP/WTA routing required")

    def predict(model, subset):
        result = np.asarray(model.predict_proba(subset), dtype=float)
        if (result.shape != (len(subset),) or not np.isfinite(result).all()
                or ((result < 0) | (result > 1)).any()):
            raise ValueError("Invalid component probabilities")
        return result

    if frame.empty:
        return np.array([], dtype=float)
    result = predict(pooled, frame).copy()
    for tour, flag in (("atp", 1), ("wta", 0)):
        weight = weights.get(tour, 0.0)
        positions = np.flatnonzero(frame.tour_atp.to_numpy() == flag)
        if weight == 0 or not len(positions):
            continue
        probability = predict(specialists[tour], frame.iloc[positions])
        result[positions] = (1 - weight) * result[positions] + weight * probability
    return result
