from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from _bootstrap import ROOT
from tbt.models.ensemble import TennisEnsemble
from tbt.models.feature_builder import (
    FEATURE_NAMES,
    FeatureBuilder,
)
from tbt.models.metrics import evaluate_probabilities
from tbt.repositories.supabase import SupabaseRepository
from tbt.services.backtest_service import _calendar_safe_split


BASE_FEATURES = [
    feature
    for feature in FEATURE_NAMES
    if feature not in {
        "fatigue_3d_advantage",
        "fatigue_7d_advantage",
        "travel_km_advantage",
        "travel_known",
        "altitude_change_advantage",
        "altitude_change_known",
        "weather_serve_interaction",
        "weather_known",
        "altitude_serve_interaction",
        "environment_known",
    }
]

VARIANTS = {
    "baseline": BASE_FEATURES,
    "fatigue": (
        BASE_FEATURES
        + [
            "fatigue_3d_advantage",
            "fatigue_7d_advantage",
        ]
    ),
    "travel": (
        BASE_FEATURES
        + [
            "travel_km_advantage",
            "travel_known",
        ]
    ),
    "altitude": (
        BASE_FEATURES
        + [
            "altitude_change_advantage",
            "altitude_change_known",
            "altitude_serve_interaction",
        ]
    ),
    "weather": (
        BASE_FEATURES
        + [
            "weather_serve_interaction",
            "weather_known",
        ]
    ),
    "environment_all": list(
        FEATURE_NAMES
    ),
}


def delta(
    metrics: dict,
    baseline: dict,
) -> dict:
    return {
        key: (
            float(metrics[key])
            - float(baseline[key])
        )
        for key in (
            "accuracy",
            "roc_auc",
            "log_loss",
            "brier_score",
            "ece_10",
        )
    }


def main() -> None:
    repo = SupabaseRepository()

    matches = repo.get_completed_matches()

    frame = (
        FeatureBuilder()
        .build_training_frame(matches)
        .sort_values(
            ["scheduled_at", "match_id"]
        )
        .reset_index(drop=True)
    )

    frame["scheduled_at"] = pd.to_datetime(
        frame["scheduled_at"],
        utc=True,
    )

    frame["year"] = (
        frame["scheduled_at"].dt.year
    )

    years = sorted(
        int(value)
        for value in frame["year"].unique()
    )

    if len(years) < 3:
        raise SystemExit(
            "Not enough years for challenger backtest"
        )

    first_test_year = max(
        years[0] + 2,
        years[-1] - 2,
    )

    report = {
        "method": (
            "calendar-year walk-forward "
            "feature-family diagnostic"
        ),
        "feature_schema": list(
            FEATURE_NAMES
        ),
        "first_test_year": first_test_year,
        "variants": {},
    }

    accumulated: dict[
        str,
        dict[str, list],
    ] = {
        name: {
            "y": [],
            "p": [],
            "folds": [],
        }
        for name in VARIANTS
    }

    for year in years:
        if year < first_test_year:
            continue

        historical = frame[
            frame["year"] < year
        ].copy()

        test = frame[
            frame["year"] == year
        ].copy()

        if len(historical) < 1200 or len(test) < 100:
            continue

        train, calibration = (
            _calendar_safe_split(
                historical
            )
        )

        for name, features in VARIANTS.items():
            model = TennisEnsemble(
                feature_names=features
            )

            model.fit(
                train,
                calibration,
            )

            probability = (
                model.predict_proba(
                    test
                )
            )

            metrics = (
                evaluate_probabilities(
                    test["target"],
                    probability,
                )
            )

            accumulated[name][
                "y"
            ].extend(
                test["target"]
                .astype(int)
                .tolist()
            )

            accumulated[name][
                "p"
            ].extend(
                probability.tolist()
            )

            accumulated[name][
                "folds"
            ].append(
                {
                    "year": year,
                    "test_rows": int(
                        len(test)
                    ),
                    "metrics": metrics,
                }
            )

    for name, result in accumulated.items():
        if not result["y"]:
            report["variants"][name] = {
                "overall": None,
                "folds": [],
            }

            continue

        overall = evaluate_probabilities(
            result["y"],
            result["p"],
        )

        report["variants"][name] = {
            "overall": overall,
            "folds": result["folds"],
        }

    baseline = report[
        "variants"
    ][
        "baseline"
    ][
        "overall"
    ]

    if baseline is None:
        raise SystemExit(
            "Baseline could not be evaluated"
        )

    for name, result in (
        report["variants"].items()
    ):
        if result["overall"] is None:
            result["delta_vs_baseline"] = None
            continue

        result["delta_vs_baseline"] = delta(
            result["overall"],
            baseline,
        )

    path = (
        ROOT
        / "reports"
        / "challenger_backtest.json"
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
