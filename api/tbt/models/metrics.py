from __future__ import annotations

import math
from typing import Iterable

import numpy as np
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

from ..utils import clamp


def calibration_bins(y_true: Iterable[int], y_prob: Iterable[float], bins: int = 10) -> list[dict]:
    y = np.asarray(list(y_true), dtype=float)
    p = np.asarray(list(y_prob), dtype=float)
    result: list[dict] = []
    edges = np.linspace(0.0, 1.0, bins + 1)
    for i in range(bins):
        lo, hi = float(edges[i]), float(edges[i + 1])
        if i == bins - 1:
            mask = (p >= lo) & (p <= hi)
        else:
            mask = (p >= lo) & (p < hi)
        count = int(mask.sum())
        if count == 0:
            continue
        result.append(
            {
                "min_probability": lo,
                "max_probability": hi,
                "count": count,
                "mean_probability": float(p[mask].mean()),
                "actual_win_rate": float(y[mask].mean()),
            }
        )
    return result


def expected_calibration_error(y_true: Iterable[int], y_prob: Iterable[float], bins: int = 10) -> float:
    rows = calibration_bins(y_true, y_prob, bins=bins)
    total = sum(row["count"] for row in rows)
    if not total:
        return float("nan")
    return float(
        sum(
            row["count"] * abs(row["mean_probability"] - row["actual_win_rate"])
            for row in rows
        )
        / total
    )


def evaluate_probabilities(y_true: Iterable[int], y_prob: Iterable[float]) -> dict:
    y = np.asarray(list(y_true), dtype=int)
    p = np.asarray([clamp(float(v), 1e-6, 1 - 1e-6) for v in y_prob], dtype=float)
    if len(y) == 0:
        return {}
    metrics = {
        "n": int(len(y)),
        "accuracy": float(accuracy_score(y, p >= 0.5)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "brier_score": float(brier_score_loss(y, p)),
        "ece_10": expected_calibration_error(y, p, bins=10),
        "mean_confidence": float(np.maximum(p, 1.0 - p).mean()),
    }
    try:
        metrics["roc_auc"] = float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else math.nan
    except ValueError:
        metrics["roc_auc"] = math.nan
    metrics["calibration_bins"] = calibration_bins(y, p, bins=10)
    metrics["selective_accuracy"] = selective_accuracy(y, p)
    return metrics


def wilson_interval(wins, n):
    if not n:
        return None
    z = 1.959963984540054
    p = wins / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [max(0., center - radius), min(1., center + radius)]


def selective_accuracy(y_true, y_prob) -> list[dict]:
    """Fixed diagnostic thresholds, never selected using holdout outcomes."""
    y, p = np.asarray(y_true), np.asarray(y_prob, dtype=float)
    if y.shape != p.shape or not np.isfinite(p).all():
        raise ValueError("Targets/probabilities must align and be finite")
    confidence = np.maximum(p, 1 - p)
    rows = []
    for threshold in (.5, .55, .6, .65, .7, .75, .8, .85, .9):
        selected = confidence >= threshold
        count = int(selected.sum())
        wins = int(((p[selected] >= .5) == y[selected]).sum())
        rows.append({"threshold": threshold, "n": count, "correct": wins,
                     "coverage": count / len(y) if len(y) else 0.,
                     "accuracy_ci95_wilson": wilson_interval(wins, count),
                     "accuracy": wins / count if count else None})
    return rows
