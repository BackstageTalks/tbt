from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from ..models.ensemble import TennisEnsemble
from ..models.feature_builder import FeatureBuilder
from ..models.metrics import evaluate_probabilities
from ..schemas import MatchRecord
from .data_quality import audit_history
from .training import _enforce_rank_provenance


def _calendar_safe_split(
    historical: pd.DataFrame,
    train_fraction: float = 0.85,
    min_calibration_rows: int = 120,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split historical data into train/calibration without cutting a
    calendar day in half.

    The calibration period is strictly later than the training period.
    """

    if historical.empty:
        raise ValueError(
            "Historical frame is empty"
        )

    ordered = historical.sort_values(
        [
            "scheduled_at",
            "match_id",
        ]
    ).reset_index(
        drop=True
    )

    ordered["_event_day"] = (
        pd.to_datetime(
            ordered["scheduled_at"],
            utc=True,
        )
        .dt.date
    )

    target_index = max(
        300,
        int(
            len(ordered)
            * train_fraction
        ),
    )

    target_index = min(
        target_index,
        len(ordered)
        - min_calibration_rows,
    )

    if target_index <= 0:
        raise ValueError(
            "Not enough historical rows "
            "for train/calibration split"
        )

    candidate_day = ordered.iloc[
        target_index
    ]["_event_day"]

    split_index = int(
        (
            ordered["_event_day"]
            < candidate_day
        ).sum()
    )

    # If moving to the previous full day makes training too small,
    # move the boundary after the candidate day instead.
    if split_index < 300:
        split_index = int(
            (
                ordered["_event_day"]
                <= candidate_day
            ).sum()
        )

    if (
        split_index < 300
        or (
            len(ordered)
            - split_index
        )
        < min_calibration_rows
    ):
        raise ValueError(
            "Unable to create a calendar-safe "
            "train/calibration split"
        )

    train = (
        ordered.iloc[
            :split_index
        ]
        .drop(
            columns=[
                "_event_day"
            ]
        )
        .copy()
    )

    calibration = (
        ordered.iloc[
            split_index:
        ]
        .drop(
            columns=[
                "_event_day"
            ]
        )
        .copy()
    )

    train_max = pd.to_datetime(
        train["scheduled_at"],
        utc=True,
    ).max()

    calibration_min = pd.to_datetime(
        calibration["scheduled_at"],
        utc=True,
    ).min()

    if (
        train_max.normalize()
        >= calibration_min.normalize()
    ):
        raise RuntimeError(
            "Calendar-safe split failed: "
            "training and calibration "
            "overlap on the same UTC day"
        )

    return (
        train,
        calibration,
    )


def _metric_delta(
    model_metrics: dict,
    baseline_metrics: dict,
    key: str,
) -> float | None:
    model_value = model_metrics.get(
        key
    )

    baseline_value = baseline_metrics.get(
        key
    )

    if (
        model_value is None
        or baseline_value is None
    ):
        return None

    return (
        float(model_value)
        - float(baseline_value)
    )


def walk_forward_backtest(
    matches: Iterable[
        MatchRecord
    ],
    min_training_rows: int = 1200,
    first_test_year: int | None = None,
) -> dict:
    matches, quality = audit_history(matches)
    matches, rank_provenance = _enforce_rank_provenance(matches)
    frame = (
        FeatureBuilder()
        .build_training_frame(
            matches
        )
    )

    if frame.empty:
        raise ValueError(
            "No completed matches for backtest"
        )

    frame = (
        frame.sort_values(
            [
                "scheduled_at",
                "match_id",
            ]
        )
        .reset_index(
            drop=True
        )
    )

    frame["scheduled_at"] = (
        pd.to_datetime(
            frame["scheduled_at"],
            utc=True,
        )
    )

    frame["year"] = (
        frame[
            "scheduled_at"
        ].dt.year
    )

    available_years = sorted(
        int(year)
        for year
        in frame[
            "year"
        ].unique()
    )

    if not available_years:
        raise ValueError(
            "No valid years available "
            "for backtest"
        )

    if first_test_year is None:
        first_test_year = max(
            available_years[0]
            + 2,
            available_years[-1]
            - 3,
        )

    folds: list[
        dict
    ] = []

    all_y: list[
        int
    ] = []

    all_p: list[
        float
    ] = []

    all_elo: list[
        float
    ] = []

    test_years = [
        year
        for year in available_years
        if year
        >= first_test_year
    ]

    for year in test_years:
        historical = (
            frame[
                frame["year"]
                < year
            ]
            .copy()
        )

        test = (
            frame[
                frame["year"]
                == year
            ]
            .copy()
        )

        if (
            len(historical)
            < min_training_rows
            or len(test)
            < 100
        ):
            continue

        (
            train,
            calibration,
        ) = _calendar_safe_split(
            historical
        )

        model = (
            TennisEnsemble()
            .fit(
                train,
                calibration,
            )
        )

        probabilities = (
            model.predict_proba(
                test
            )
        )

        elo = (
            test[
                "elo_probability"
            ]
            .astype(float)
            .clip(
                0.01,
                0.99,
            )
            .to_numpy()
        )

        target = (
            test[
                "target"
            ]
            .astype(int)
        )

        metrics = (
            evaluate_probabilities(
                target,
                probabilities,
            )
        )

        baseline = (
            evaluate_probabilities(
                target,
                elo,
            )
        )

        train_start = (
            train[
                "scheduled_at"
            ].min()
        )

        train_end = (
            train[
                "scheduled_at"
            ].max()
        )

        calibration_start = (
            calibration[
                "scheduled_at"
            ].min()
        )

        calibration_end = (
            calibration[
                "scheduled_at"
            ].max()
        )

        test_start = (
            test[
                "scheduled_at"
            ].min()
        )

        test_end = (
            test[
                "scheduled_at"
            ].max()
        )

        folds.append(
            {
                "year": (
                    year
                ),
                "train_rows": int(
                    len(train)
                ),
                "calibration_rows": int(
                    len(calibration)
                ),
                "test_rows": int(
                    len(test)
                ),
                "periods": {
                    "train_start": (
                        train_start.isoformat()
                    ),
                    "train_end": (
                        train_end.isoformat()
                    ),
                    "calibration_start": (
                        calibration_start.isoformat()
                    ),
                    "calibration_end": (
                        calibration_end.isoformat()
                    ),
                    "test_start": (
                        test_start.isoformat()
                    ),
                    "test_end": (
                        test_end.isoformat()
                    ),
                },
                "model": (
                    metrics
                ),
                "elo_baseline": (
                    baseline
                ),
                "delta_vs_elo": {
                    "accuracy": (
                        _metric_delta(
                            metrics,
                            baseline,
                            "accuracy",
                        )
                    ),
                    "roc_auc": (
                        _metric_delta(
                            metrics,
                            baseline,
                            "roc_auc",
                        )
                    ),
                    "log_loss": (
                        _metric_delta(
                            metrics,
                            baseline,
                            "log_loss",
                        )
                    ),
                    "brier_score": (
                        _metric_delta(
                            metrics,
                            baseline,
                            "brier_score",
                        )
                    ),
                    "ece_10": (
                        _metric_delta(
                            metrics,
                            baseline,
                            "ece_10",
                        )
                    ),
                },
                "model_metadata": dict(
                    model.metadata
                ),
            }
        )

        all_y.extend(
            target.tolist()
        )

        all_p.extend(
            probabilities.tolist()
        )

        all_elo.extend(
            elo.tolist()
        )

    if not folds:
        raise ValueError(
            "Not enough history to create "
            "walk-forward folds"
        )

    overall = (
        evaluate_probabilities(
            all_y,
            all_p,
        )
    )

    elo_overall = (
        evaluate_probabilities(
            all_y,
            all_elo,
        )
    )

    return {
        "data_quality": quality,
        "rank_provenance": rank_provenance,
        "method": (
            "calendar-year walk-forward; "
            "every test year is strictly later "
            "than training/calibration; "
            "train/calibration boundaries never "
            "split a UTC calendar day"
        ),
        "first_test_year": (
            first_test_year
        ),
        "folds": (
            folds
        ),
        "overall": (
            overall
        ),
        "elo_baseline_overall": (
            elo_overall
        ),
        "delta_vs_elo": {
            "accuracy": (
                _metric_delta(
                    overall,
                    elo_overall,
                    "accuracy",
                )
            ),
            "roc_auc": (
                _metric_delta(
                    overall,
                    elo_overall,
                    "roc_auc",
                )
            ),
            "log_loss": (
                _metric_delta(
                    overall,
                    elo_overall,
                    "log_loss",
                )
            ),
            "brier_score": (
                _metric_delta(
                    overall,
                    elo_overall,
                    "brier_score",
                )
            ),
            "ece_10": (
                _metric_delta(
                    overall,
                    elo_overall,
                    "ece_10",
                )
            ),
        },
        "tested_matches": int(
            len(all_y)
        ),
    }
