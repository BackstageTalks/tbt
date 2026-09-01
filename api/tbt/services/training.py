from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from typing import Iterable

import pandas as pd

from ..models.ensemble import TennisEnsemble
from ..models.feature_builder import FeatureBuilder
from ..models.metrics import evaluate_probabilities
from ..schemas import MatchRecord


@dataclass
class TrainingResult:
    model: TennisEnsemble
    report: dict
    feature_frame: pd.DataFrame


def _split_by_date(frame: pd.DataFrame, train_fraction: float, calibration_fraction: float):
    if frame.empty:
        raise ValueError("No training rows")
    ordered = frame.sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)
    days = sorted(pd.to_datetime(ordered["scheduled_at"], utc=True).dt.date.unique())
    if len(days) < 30:
        raise ValueError("Training history must span at least 30 distinct dates")
    train_day_idx = max(1, int(len(days) * train_fraction))
    cal_day_idx = max(train_day_idx + 1, int(len(days) * (train_fraction + calibration_fraction)))
    cal_day_idx = min(cal_day_idx, len(days) - 1)
    train_end = days[train_day_idx - 1]
    cal_end = days[cal_day_idx - 1]
    row_days = pd.to_datetime(ordered["scheduled_at"], utc=True).dt.date
    train = ordered[row_days <= train_end].copy()
    calibration = ordered[(row_days > train_end) & (row_days <= cal_end)].copy()
    test = ordered[row_days > cal_end].copy()
    return train, calibration, test


def _group_metrics(frame: pd.DataFrame, probabilities) -> dict:
    result: dict = {}
    scored = frame.copy()
    scored["probability"] = probabilities
    for column in ("tour", "surface"):
        result[column] = {}
        for value, group in scored.groupby(column):
            if len(group) < 50:
                continue
            result[column][str(value)] = evaluate_probabilities(
                group["target"], group["probability"]
            )
    return result


def train_from_matches(
    matches: Iterable[MatchRecord],
    min_matches: int = 2500,
) -> TrainingResult:
    builder = FeatureBuilder()
    frame = builder.build_training_frame(matches)
    if len(frame) < min_matches:
        raise ValueError(
            f"Only {len(frame)} completed matches available; at least {min_matches} are required"
        )

    train, calibration, test = _split_by_date(frame, 0.70, 0.15)
    evaluation_model = TennisEnsemble().fit(train, calibration)
    test_p = evaluation_model.predict_proba(test)
    elo_p = test["elo_probability"].astype(float).clip(0.01, 0.99).to_numpy()

    report = {
        "data": {
            "matches_total": int(len(frame)),
            "train": int(len(train)),
            "calibration": int(len(calibration)),
            "holdout": int(len(test)),
            "start": pd.to_datetime(frame["scheduled_at"], utc=True).min().isoformat(),
            "end": pd.to_datetime(frame["scheduled_at"], utc=True).max().isoformat(),
            "target_rate": float(frame["target"].mean()),
        },
        "holdout": evaluate_probabilities(test["target"], test_p),
        "elo_baseline_holdout": evaluate_probabilities(test["target"], elo_p),
        "subgroups": _group_metrics(test, test_p),
    }

    # Production fit uses all available history, keeping only the newest slice for calibration.
    # This gives the deployed model more recent information without contaminating the holdout report.
    production_train, production_cal, _ = _split_by_date(frame, 0.84, 0.15)
    remainder = frame.loc[~frame.index.isin(production_train.index) & ~frame.index.isin(production_cal.index)]
    if not remainder.empty:
        production_cal = pd.concat([production_cal, remainder]).sort_values("scheduled_at")
    production_model = TennisEnsemble().fit(production_train, production_cal)
    production_model.metadata = {
        "model_version": production_model.version,
        "trained_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "training_matches": int(len(frame)),
        "history_start": report["data"]["start"],
        "history_end": report["data"]["end"],
        "holdout_metrics": report["holdout"],
        "elo_baseline_metrics": report["elo_baseline_holdout"],
        "target_rate": report["data"]["target_rate"],
        **production_model.metadata,
    }
    return TrainingResult(production_model, report, frame)
