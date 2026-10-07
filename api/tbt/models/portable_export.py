"""Offline export of a fitted TennisEnsemble into a pure-JSON serving model."""
from __future__ import annotations

from typing import Any

from .symmetry import INVARIANT_FEATURES, SWAP_PAIRS


def _floats(values) -> list[float]:
    return [float(value) for value in values]


def _export_tree(predictor) -> list[dict[str, Any]]:
    rows = []
    for node in predictor.nodes:
        rows.append({
            "value": float(node["value"]),
            "feature": int(node["feature_idx"]),
            "threshold": float(node["num_threshold"]),
            "missing_left": bool(node["missing_go_to_left"]),
            "left": int(node["left"]),
            "right": int(node["right"]),
            "leaf": bool(node["is_leaf"]),
        })
    return rows


def _export_calibrator(calibrator) -> dict[str, Any]:
    kind = str(getattr(calibrator, "kind", "identity") or "identity")
    model = getattr(calibrator, "model", None)
    if kind == "identity" or model is None:
        return {"kind": "identity"}
    if kind == "platt":
        coef = float(model.coef_.reshape(-1)[0])
        intercept = float(model.intercept_.reshape(-1)[0]) if getattr(model, "fit_intercept", True) else 0.0
        return {"kind": "platt", "coef": coef, "intercept": intercept}
    if kind == "isotonic":
        return {
            "kind": "isotonic",
            "x_thresholds": _floats(model.X_thresholds_),
            "y_thresholds": _floats(model.y_thresholds_),
        }
    raise ValueError(f"unsupported calibrator kind: {kind}")


def export_portable_model(model) -> dict[str, Any]:
    """Serialize only inference state required by :mod:`portable_model`.

    The returned object is JSON-compatible and contains no pickle/joblib payload.
    """
    if not bool(getattr(model, "fitted", False)):
        raise ValueError("model must be fitted")
    feature_names = list(getattr(model, "feature_names", None) or ())
    if not feature_names:
        raise ValueError("model contains no feature names")

    scale = model.linear.named_steps["scale"]
    linear = model.linear.named_steps["model"]
    if len(getattr(linear, "classes_", ())) != 2:
        raise ValueError("portable scorer supports binary logistic regression only")

    predictors = getattr(model.boost, "_predictors", None)
    if not predictors:
        raise ValueError("boost model contains no fitted predictors")
    trees = []
    for iteration in predictors:
        if len(iteration) != 1:
            raise ValueError("portable scorer supports binary HistGradientBoosting only")
        trees.append(_export_tree(iteration[0]))

    baseline = float(model.boost._baseline_prediction.reshape(-1)[0])
    artifact = {
        "schema": 1,
        "model_version": str(getattr(model, "version", "") or ""),
        "feature_names": feature_names,
        "excluded_features": sorted(set(getattr(model, "excluded_features", set()) or set())),
        "symmetric_inference": bool((getattr(model, "metadata", {}) or {}).get("symmetric_inference", False)),
        "blend_weight_boost": float(getattr(model, "blend_weight", 0.5)),
        "elo_weight": float(getattr(model, "elo_weight", 0.0)),
        "linear": {
            "mean": _floats(scale.mean_),
            "scale": _floats(scale.scale_),
            "coef": _floats(linear.coef_.reshape(-1)),
            "intercept": float(linear.intercept_.reshape(-1)[0]),
        },
        "boost": {
            "baseline": baseline,
            "trees": trees,
        },
        "calibrator": _export_calibrator(model.calibrator),
        "swap": {
            "invariant": sorted(name for name in feature_names if name in INVARIANT_FEATURES),
            "probability": sorted(
                name for name in feature_names
                if name in {"elo_probability", "season_yelo_probability"}
            ),
            "pairs": {
                name: other for name, other in SWAP_PAIRS.items()
                if name in feature_names and other in feature_names
            },
        },
    }
    return artifact
