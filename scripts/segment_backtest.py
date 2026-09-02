from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from _bootstrap import ROOT

import tbt.models.ensemble as ensemble_module
from tbt.models.ensemble import TennisEnsemble
from tbt.models.feature_builder import FeatureBuilder
from tbt.models.metrics import evaluate_probabilities
from tbt.repositories.supabase import SupabaseRepository


BASE_FEATURES = [
    "elo_diff",
    "surface_elo_diff",
    "elo_probability",
    "experience_diff",
    "recent_form_diff",
    "medium_form_diff",
    "opponent_adjusted_form_diff",
    "surface_form_diff",
    "rank_advantage",
    "rank_known_both",
    "rest_advantage",
    "layoff_advantage",
    "h2h_advantage",
    "serve_quality_diff",
    "return_quality_diff",
    "stats_known_both",
    "tournament_level",
    "best_of_five",
    "indoor",
    "tour_atp",
    "data_depth",
]


CONFIDENCE_BUCKETS = [
    (0.50, 0.55, "50-55"),
    (0.55, 0.60, "55-60"),
    (0.60, 0.65, "60-65"),
    (0.65, 0.70, "65-70"),
    (0.70, 0.75, "70-75"),
    (0.75, 0.80, "75-80"),
    (0.80, 1.01, "80+"),
]


def _fit_model(
    train: pd.DataFrame,
    calibration: pd.DataFrame,
    test: pd.DataFrame,
) -> np.ndarray:
    original_features = getattr(
        ensemble_module,
        "FEATURE_NAMES",
        None,
    )

    try:
        ensemble_module.FEATURE_NAMES = list(
            BASE_FEATURES
        )

        model = TennisEnsemble().fit(
            train,
            calibration,
        )

        return np.asarray(
            model.predict_proba(test),
            dtype=float,
        )

    finally:
        if original_features is not None:
            ensemble_module.FEATURE_NAMES = (
                original_features
            )


def _safe_metrics(
    y: pd.Series | np.ndarray | list,
    probability: pd.Series | np.ndarray | list,
) -> dict[str, Any] | None:
    y_array = np.asarray(
        y,
        dtype=int,
    )

    p_array = np.asarray(
        probability,
        dtype=float,
    )

    if len(y_array) == 0:
        return None

    try:
        return evaluate_probabilities(
            y_array,
            p_array,
        )

    except Exception as exc:
        return {
            "n": int(len(y_array)),
            "error": str(exc),
        }


def _comparison(
    frame: pd.DataFrame,
) -> dict[str, Any]:
    if frame.empty:
        return {
            "n": 0,
            "model": None,
            "ta_elo": None,
            "delta_vs_ta_elo": None,
        }

    model_metrics = _safe_metrics(
        frame["target"],
        frame["model_probability"],
    )

    elo_metrics = _safe_metrics(
        frame["target"],
        frame["elo_probability"],
    )

    delta = None

    if (
        model_metrics
        and elo_metrics
        and "error" not in model_metrics
        and "error" not in elo_metrics
    ):
        delta = {
            "accuracy": (
                model_metrics["accuracy"]
                - elo_metrics["accuracy"]
            ),
            "roc_auc": (
                model_metrics["roc_auc"]
                - elo_metrics["roc_auc"]
            ),
            "log_loss": (
                model_metrics["log_loss"]
                - elo_metrics["log_loss"]
            ),
            "brier_score": (
                model_metrics["brier_score"]
                - elo_metrics["brier_score"]
            ),
            "ece_10": (
                model_metrics["ece_10"]
                - elo_metrics["ece_10"]
            ),
        }

    return {
        "n": int(len(frame)),
        "model": model_metrics,
        "ta_elo": elo_metrics,
        "delta_vs_ta_elo": delta,
    }


def _segment(
    frame: pd.DataFrame,
    column: str,
    value: str,
) -> dict[str, Any]:
    subset = frame[
        frame[column].astype(str).str.lower()
        == value.lower()
    ]

    return _comparison(
        subset
    )


def main() -> None:
    repo = SupabaseRepository()

    matches = repo.get_completed_matches()

    print(
        f"Loaded {len(matches)} canonical completed matches"
    )

    frame = (
        FeatureBuilder()
        .build_training_frame(
            matches
        )
    )

    if frame.empty:
        raise SystemExit(
            "FeatureBuilder returned no rows"
        )

    missing = [
        column
        for column in BASE_FEATURES
        if column not in frame.columns
    ]

    if missing:
        raise SystemExit(
            "Missing baseline features: "
            + ", ".join(missing)
        )

    frame = frame.sort_values(
        [
            "scheduled_at",
            "match_id",
        ]
    ).reset_index(
        drop=True
    )

    frame["year"] = (
        pd.to_datetime(
            frame["scheduled_at"],
            utc=True,
        )
        .dt.year
    )

    years = sorted(
        int(year)
        for year
        in frame["year"].unique()
    )

    if not years:
        raise SystemExit(
            "No years found"
        )

    first_test_year = max(
        years[0] + 2,
        years[-1] - 3,
    )

    test_predictions = []

    folds = []

    for year in years:
        if year < first_test_year:
            continue

        historical = frame[
            frame["year"] < year
        ].copy()

        test = frame[
            frame["year"] == year
        ].copy()

        if len(historical) < 1200:
            continue

        if len(test) < 100:
            continue

        historical = historical.sort_values(
            [
                "scheduled_at",
                "match_id",
            ]
        )

        split = max(
            300,
            int(
                len(historical)
                * 0.85
            ),
        )

        split = min(
            split,
            len(historical) - 120,
        )

        train = historical.iloc[
            :split
        ].copy()

        calibration = historical.iloc[
            split:
        ].copy()

        probabilities = _fit_model(
            train,
            calibration,
            test,
        )

        test = test.copy()

        test[
            "model_probability"
        ] = probabilities

        test[
            "model_confidence"
        ] = np.maximum(
            probabilities,
            1.0 - probabilities,
        )

        test_predictions.append(
            test
        )

        folds.append(
            {
                "year": int(year),
                "train_rows": int(
                    len(train)
                ),
                "calibration_rows": int(
                    len(calibration)
                ),
                "test_rows": int(
                    len(test)
                ),
            }
        )

        print(
            f"Fold {year}: "
            f"train={len(train)}, "
            f"calibration={len(calibration)}, "
            f"test={len(test)}"
        )

    if not test_predictions:
        raise SystemExit(
            "No valid walk-forward folds"
        )

    tested = pd.concat(
        test_predictions,
        ignore_index=True,
    )

    report: dict[str, Any] = {
        "method": (
            "calendar-year walk-forward; "
            "every test match is strictly later "
            "than training/calibration"
        ),
        "first_test_year": int(
            first_test_year
        ),
        "tested_matches": int(
            len(tested)
        ),
        "folds": folds,
        "overall": _comparison(
            tested
        ),
        "tour": {},
        "surface": {},
        "confidence": {},
    }

    for tour in (
        "atp",
        "wta",
    ):
        report[
            "tour"
        ][tour.upper()] = _segment(
            tested,
            "tour",
            tour,
        )

    surfaces = sorted(
        value
        for value in (
            tested[
                "surface"
            ]
            .dropna()
            .astype(str)
            .str.lower()
            .unique()
        )
        if value
    )

    for surface in surfaces:
        report[
            "surface"
        ][surface] = _segment(
            tested,
            "surface",
            surface,
        )

    for (
        lower,
        upper,
        label,
    ) in CONFIDENCE_BUCKETS:
        subset = tested[
            (
                tested[
                    "model_confidence"
                ]
                >= lower
            )
            & (
                tested[
                    "model_confidence"
                ]
                < upper
            )
        ]

        result = _comparison(
            subset
        )

        if not subset.empty:
            predicted_winner_correct = (
                (
                    (
                        subset[
                            "model_probability"
                        ]
                        >= 0.5
                    )
                    & (
                        subset[
                            "target"
                        ]
                        == 1
                    )
                )
                |
                (
                    (
                        subset[
                            "model_probability"
                        ]
                        < 0.5
                    )
                    & (
                        subset[
                            "target"
                        ]
                        == 0
                    )
                )
            )

            result[
                "pick_accuracy"
            ] = float(
                predicted_winner_correct.mean()
            )

            result[
                "mean_confidence"
            ] = float(
                subset[
                    "model_confidence"
                ].mean()
            )

        else:
            result[
                "pick_accuracy"
            ] = None

            result[
                "mean_confidence"
            ] = None

        report[
            "confidence"
        ][label] = result

    path = (
        ROOT
        / "reports"
        / "segment_backtest.json"
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
