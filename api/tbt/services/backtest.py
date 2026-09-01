from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from ..models.ensemble import TennisEnsemble
from ..models.feature_builder import FeatureBuilder
from ..models.metrics import evaluate_probabilities
from ..schemas import MatchRecord


def walk_forward_backtest(
    matches: Iterable[MatchRecord],
    min_training_rows: int = 1200,
    first_test_year: int | None = None,
) -> dict:
    frame = FeatureBuilder().build_training_frame(matches)
    if frame.empty:
        raise ValueError("No completed matches for backtest")
    frame = frame.sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)
    frame["year"] = pd.to_datetime(frame["scheduled_at"], utc=True).dt.year
    available_years = sorted(int(y) for y in frame["year"].unique())
    if first_test_year is None:
        first_test_year = max(available_years[0] + 2, available_years[-1] - 3)

    folds: list[dict] = []
    all_y: list[int] = []
    all_p: list[float] = []
    all_elo: list[float] = []

    for year in [y for y in available_years if y >= first_test_year]:
        historical = frame[frame["year"] < year].copy()
        test = frame[frame["year"] == year].copy()
        if len(historical) < min_training_rows or len(test) < 100:
            continue

        historical = historical.sort_values("scheduled_at")
        split = max(300, int(len(historical) * 0.85))
        split = min(split, len(historical) - 120)
        train = historical.iloc[:split].copy()
        calibration = historical.iloc[split:].copy()
        model = TennisEnsemble().fit(train, calibration)
        p = model.predict_proba(test)
        elo = test["elo_probability"].astype(float).clip(0.01, 0.99).to_numpy()

        metrics = evaluate_probabilities(test["target"], p)
        baseline = evaluate_probabilities(test["target"], elo)
        folds.append(
            {
                "year": year,
                "train_rows": int(len(train)),
                "calibration_rows": int(len(calibration)),
                "test_rows": int(len(test)),
                "model": metrics,
                "elo_baseline": baseline,
                "log_loss_delta_vs_elo": metrics["log_loss"] - baseline["log_loss"],
                "brier_delta_vs_elo": metrics["brier_score"] - baseline["brier_score"],
            }
        )
        all_y.extend(test["target"].astype(int).tolist())
        all_p.extend(p.tolist())
        all_elo.extend(elo.tolist())

    if not folds:
        raise ValueError("Not enough history to create walk-forward folds")

    overall = evaluate_probabilities(all_y, all_p)
    elo_overall = evaluate_probabilities(all_y, all_elo)
    return {
        "method": "calendar-year walk-forward; every test year is strictly later than training/calibration",
        "first_test_year": first_test_year,
        "folds": folds,
        "overall": overall,
        "elo_baseline_overall": elo_overall,
        "log_loss_delta_vs_elo": overall["log_loss"] - elo_overall["log_loss"],
        "brier_delta_vs_elo": overall["brier_score"] - elo_overall["brier_score"],
        "tested_matches": int(len(all_y)),
    }
