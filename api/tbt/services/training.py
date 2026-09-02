from __future__ import annotations

from dataclasses import dataclass
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


def _split_by_date(
    frame: pd.DataFrame,
    train_fraction: float,
    calibration_fraction: float,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """
    Split chronologically by whole UTC calendar days.

    No calendar day can appear in more than one partition.
    """

    if frame.empty:
        raise ValueError(
            "No training rows"
        )

    if (
        train_fraction <= 0.0
        or calibration_fraction <= 0.0
        or (
            train_fraction
            + calibration_fraction
        )
        >= 1.0
    ):
        raise ValueError(
            "Invalid train/calibration fractions"
        )

    ordered = (
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

    timestamps = pd.to_datetime(
        ordered["scheduled_at"],
        utc=True,
    )

    row_days = timestamps.dt.date

    days = sorted(
        row_days.unique()
    )

    if len(days) < 30:
        raise ValueError(
            "Training history must span "
            "at least 30 distinct dates"
        )

    train_day_idx = max(
        1,
        int(
            len(days)
            * train_fraction
        ),
    )

    cal_day_idx = max(
        train_day_idx + 1,
        int(
            len(days)
            * (
                train_fraction
                + calibration_fraction
            )
        ),
    )

    cal_day_idx = min(
        cal_day_idx,
        len(days) - 1,
    )

    train_end = days[
        train_day_idx - 1
    ]

    calibration_end = days[
        cal_day_idx - 1
    ]

    train = (
        ordered[
            row_days
            <= train_end
        ]
        .copy()
    )

    calibration = (
        ordered[
            (
                row_days
                > train_end
            )
            & (
                row_days
                <= calibration_end
            )
        ]
        .copy()
    )

    test = (
        ordered[
            row_days
            > calibration_end
        ]
        .copy()
    )

    if train.empty:
        raise ValueError(
            "Training partition is empty"
        )

    if calibration.empty:
        raise ValueError(
            "Calibration partition is empty"
        )

    if test.empty:
        raise ValueError(
            "Holdout partition is empty"
        )

    train_last_day = (
        pd.to_datetime(
            train["scheduled_at"],
            utc=True,
        )
        .max()
        .normalize()
    )

    calibration_first_day = (
        pd.to_datetime(
            calibration["scheduled_at"],
            utc=True,
        )
        .min()
        .normalize()
    )

    calibration_last_day = (
        pd.to_datetime(
            calibration["scheduled_at"],
            utc=True,
        )
        .max()
        .normalize()
    )

    test_first_day = (
        pd.to_datetime(
            test["scheduled_at"],
            utc=True,
        )
        .min()
        .normalize()
    )

    if (
        train_last_day
        >= calibration_first_day
    ):
        raise RuntimeError(
            "Training/calibration date overlap"
        )

    if (
        calibration_last_day
        >= test_first_day
    ):
        raise RuntimeError(
            "Calibration/holdout date overlap"
        )

    return (
        train,
        calibration,
        test,
    )


def _group_metrics(
    frame: pd.DataFrame,
    probabilities,
) -> dict:
    result: dict = {}

    scored = frame.copy()

    scored[
        "probability"
    ] = probabilities

    for column in (
        "tour",
        "surface",
    ):
        result[
            column
        ] = {}

        for (
            value,
            group,
        ) in scored.groupby(
            column
        ):
            if len(group) < 50:
                continue

            result[
                column
            ][
                str(value)
            ] = (
                evaluate_probabilities(
                    group["target"],
                    group[
                        "probability"
                    ],
                )
            )

    return result


def _metric_delta(
    model_metrics: dict,
    baseline_metrics: dict,
    key: str,
) -> float | None:
    model_value = (
        model_metrics.get(
            key
        )
    )

    baseline_value = (
        baseline_metrics.get(
            key
        )
    )

    if (
        model_value is None
        or baseline_value is None
    ):
        return None

    return (
        float(model_value)
        - float(
            baseline_value
        )
    )


def _period(
    frame: pd.DataFrame,
) -> dict[str, str]:
    timestamps = pd.to_datetime(
        frame[
            "scheduled_at"
        ],
        utc=True,
    )

    return {
        "start": (
            timestamps
            .min()
            .isoformat()
        ),
        "end": (
            timestamps
            .max()
            .isoformat()
        ),
    }


def train_from_matches(
    matches: Iterable[
        MatchRecord
    ],
    min_matches: int = 2500,
) -> TrainingResult:
    builder = FeatureBuilder()

    frame = (
        builder
        .build_training_frame(
            matches
        )
    )

    if (
        len(frame)
        < min_matches
    ):
        raise ValueError(
            f"Only {len(frame)} completed "
            "matches available; at least "
            f"{min_matches} are required"
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

    # -------------------------------------------------
    # Strict out-of-time evaluation
    # 70% train / 15% calibration / 15% holdout
    # -------------------------------------------------

    (
        train,
        calibration,
        test,
    ) = _split_by_date(
        frame,
        0.70,
        0.15,
    )

    evaluation_model = (
        TennisEnsemble()
        .fit(
            train,
            calibration,
        )
    )

    test_p = (
        evaluation_model
        .predict_proba(
            test
        )
    )

    elo_p = (
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

    holdout_metrics = (
        evaluate_probabilities(
            test[
                "target"
            ],
            test_p,
        )
    )

    elo_holdout_metrics = (
        evaluate_probabilities(
            test[
                "target"
            ],
            elo_p,
        )
    )

    holdout_delta = {
        "accuracy": (
            _metric_delta(
                holdout_metrics,
                elo_holdout_metrics,
                "accuracy",
            )
        ),
        "roc_auc": (
            _metric_delta(
                holdout_metrics,
                elo_holdout_metrics,
                "roc_auc",
            )
        ),
        "log_loss": (
            _metric_delta(
                holdout_metrics,
                elo_holdout_metrics,
                "log_loss",
            )
        ),
        "brier_score": (
            _metric_delta(
                holdout_metrics,
                elo_holdout_metrics,
                "brier_score",
            )
        ),
        "ece_10": (
            _metric_delta(
                holdout_metrics,
                elo_holdout_metrics,
                "ece_10",
            )
        ),
    }

    report = {
        "method": (
            "strict chronological split by "
            "whole UTC calendar days"
        ),
        "data": {
            "matches_total": int(
                len(frame)
            ),
            "train": int(
                len(train)
            ),
            "calibration": int(
                len(calibration)
            ),
            "holdout": int(
                len(test)
            ),
            "start": (
                pd.to_datetime(
                    frame[
                        "scheduled_at"
                    ],
                    utc=True,
                )
                .min()
                .isoformat()
            ),
            "end": (
                pd.to_datetime(
                    frame[
                        "scheduled_at"
                    ],
                    utc=True,
                )
                .max()
                .isoformat()
            ),
            "target_rate": float(
                frame[
                    "target"
                ].mean()
            ),
        },
        "periods": {
            "train": (
                _period(
                    train
                )
            ),
            "calibration": (
                _period(
                    calibration
                )
            ),
            "holdout": (
                _period(
                    test
                )
            ),
        },
        "holdout": (
            holdout_metrics
        ),
        "elo_baseline_holdout": (
            elo_holdout_metrics
        ),
        "delta_vs_elo": (
            holdout_delta
        ),
        "subgroups": (
            _group_metrics(
                test,
                test_p,
            )
        ),
        "evaluation_model": {
            "blend_weight_boost": (
                evaluation_model
                .blend_weight
            ),
            "calibration_method": (
                evaluation_model
                .calibrator
                .kind
            ),
        },
    }

    # -------------------------------------------------
    # Production/challenger fit
    # -------------------------------------------------
    #
    # The holdout above remains untouched and is used only for the
    # evaluation report.
    #
    # Once evaluation is complete, the model intended for inference
    # can use the entire available history. We retain the newest
    # portion as calibration data, with all earlier data used for
    # fitting the base models.
    #
    # This does not modify the already-computed holdout metrics.
    # -------------------------------------------------

    (
        production_train,
        production_calibration,
        production_tail,
    ) = _split_by_date(
        frame,
        0.84,
        0.15,
    )

    # _split_by_date deliberately leaves the newest ~1% as a third
    # partition. For the final inference model there is no further
    # evaluation performed on this data, so it can safely become part
    # of the newest calibration period.
    production_calibration = (
        pd.concat(
            [
                production_calibration,
                production_tail,
            ],
            ignore_index=True,
        )
        .sort_values(
            [
                "scheduled_at",
                "match_id",
            ]
        )
        .reset_index(
            drop=True
        )
    )

    production_model = (
        TennisEnsemble()
        .fit(
            production_train,
            production_calibration,
        )
    )

    production_model.metadata = {
        "model_version": (
            production_model.version
        ),
        "trained_at": (
            pd.Timestamp.now(
                tz="UTC"
            ).isoformat()
        ),
        "training_matches": int(
            len(frame)
        ),
        "production_train_matches": int(
            len(
                production_train
            )
        ),
        "production_calibration_matches": int(
            len(
                production_calibration
            )
        ),
        "history_start": (
            report[
                "data"
            ][
                "start"
            ]
        ),
        "history_end": (
            report[
                "data"
            ][
                "end"
            ]
        ),
        "holdout_metrics": (
            holdout_metrics
        ),
        "elo_baseline_metrics": (
            elo_holdout_metrics
        ),
        "holdout_delta_vs_elo": (
            holdout_delta
        ),
        "target_rate": (
            report[
                "data"
            ][
                "target_rate"
            ]
        ),
        "evaluation_method": (
            report[
                "method"
            ]
        ),
        **production_model.metadata,
    }

    return TrainingResult(
        production_model,
        report,
        frame,
    )
