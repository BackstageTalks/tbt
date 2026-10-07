"""Pure-Python serving evaluator for exported BlinQ champion models.

This module intentionally imports only the Python standard library so it is safe
for the lightweight Azure Functions runtime. Export happens offline in
:mod:`tbt.models.portable_export`.
"""
from __future__ import annotations

import bisect
import math
from typing import Mapping, Sequence


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _sigmoid(value: float) -> float:
    value = float(value)
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _logit(probability: float) -> float:
    p = _clip(probability, 1e-6, 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def _interp(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    if not xs or len(xs) != len(ys):
        raise ValueError("invalid isotonic calibration thresholds")
    value = float(x)
    if value <= float(xs[0]):
        return float(ys[0])
    if value >= float(xs[-1]):
        return float(ys[-1])
    right = bisect.bisect_right(xs, value)
    left = right - 1
    x0, x1 = float(xs[left]), float(xs[right])
    y0, y1 = float(ys[left]), float(ys[right])
    if x1 <= x0:
        return y1
    weight = (value - x0) / (x1 - x0)
    return y0 + weight * (y1 - y0)


def _calibrate(calibrator: Mapping, probability: float) -> float:
    kind = str(calibrator.get("kind") or "identity")
    p = _clip(probability, 1e-6, 1.0 - 1e-6)
    if kind == "identity":
        return p
    if kind == "platt":
        coef = float(calibrator.get("coef", 1.0))
        intercept = float(calibrator.get("intercept", 0.0))
        return _sigmoid(coef * _logit(p) + intercept)
    if kind == "isotonic":
        return _interp(
            p,
            calibrator.get("x_thresholds") or (),
            calibrator.get("y_thresholds") or (),
        )
    raise ValueError(f"unsupported calibrator kind: {kind}")


def _tree_value(tree: Sequence[Mapping], vector: Sequence[float]) -> float:
    index = 0
    while True:
        node = tree[index]
        if bool(node.get("leaf")):
            return float(node.get("value", 0.0))
        feature_idx = int(node["feature"])
        value = float(vector[feature_idx])
        if not math.isfinite(value):
            go_left = bool(node.get("missing_left"))
        else:
            go_left = value <= float(node["threshold"])
        index = int(node["left"] if go_left else node["right"])


def _raw_estimators(artifact: Mapping, vector: Sequence[float]) -> tuple[float, float]:
    linear = artifact["linear"]
    mean = linear["mean"]
    scale = linear["scale"]
    coef = linear["coef"]
    intercept = float(linear.get("intercept", 0.0))
    linear_score = intercept
    for idx, value in enumerate(vector):
        denominator = float(scale[idx])
        normalized = (float(value) - float(mean[idx])) / denominator if denominator else 0.0
        linear_score += normalized * float(coef[idx])
    linear_probability = _sigmoid(linear_score)

    boost = artifact["boost"]
    raw = float(boost.get("baseline", 0.0))
    for tree in boost.get("trees") or ():
        raw += _tree_value(tree, vector)
    boost_probability = _sigmoid(raw)
    return linear_probability, boost_probability


def _swap_features(artifact: Mapping, features: Mapping[str, float]) -> dict[str, float]:
    invariants = set(artifact.get("swap", {}).get("invariant") or ())
    probability_features = set(artifact.get("swap", {}).get("probability") or ())
    pairs = artifact.get("swap", {}).get("pairs") or {}
    result = dict(features)
    for name in artifact["feature_names"]:
        value = float(features.get(name, 0.0) or 0.0)
        if name in pairs:
            result[name] = float(features.get(str(pairs[name]), 0.0) or 0.0)
        elif name in probability_features:
            result[name] = 1.0 - value
        elif name not in invariants:
            result[name] = -value
        else:
            result[name] = value
    return result


def _matrix_vector(artifact: Mapping, features: Mapping[str, float]) -> list[float]:
    excluded = set(artifact.get("excluded_features") or ())
    vector = []
    for name in artifact["feature_names"]:
        value = 0.0 if name in excluded else float(features.get(name, 0.0) or 0.0)
        if not math.isfinite(value):
            raise ValueError(f"non-finite model feature: {name}")
        vector.append(value)
    return vector


def predict_probability(artifact: Mapping, features: Mapping[str, float]) -> float:
    """Return P(player1 wins) with the same symmetric ensemble contract."""
    if int(artifact.get("schema", 0)) != 1:
        raise ValueError("unsupported portable model schema")
    vector = _matrix_vector(artifact, features)
    linear, boost = _raw_estimators(artifact, vector)

    symmetric = bool(artifact.get("symmetric_inference", False))
    if symmetric:
        swapped = _swap_features(artifact, features)
        reverse_vector = _matrix_vector(artifact, swapped)
        reverse_linear, reverse_boost = _raw_estimators(artifact, reverse_vector)
        linear = 0.5 * (linear + 1.0 - reverse_linear)
        boost = 0.5 * (boost + 1.0 - reverse_boost)

    blend_weight = float(artifact.get("blend_weight_boost", 0.5))
    probability = blend_weight * boost + (1.0 - blend_weight) * linear

    elo_weight = float(artifact.get("elo_weight", 0.0))
    if elo_weight:
        elo_probability = float(features.get("elo_probability", 0.5) or 0.5)
        probability = (1.0 - elo_weight) * probability + elo_weight * elo_probability

    probability = _clip(probability, 0.01, 0.99)
    calibrator = artifact.get("calibrator") or {"kind": "identity"}
    if symmetric:
        calibrated = 0.5 * (
            _calibrate(calibrator, probability)
            + 1.0
            - _calibrate(calibrator, 1.0 - probability)
        )
    else:
        calibrated = _calibrate(calibrator, probability)
    return _clip(calibrated, 0.01, 0.99)
