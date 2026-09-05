from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from _bootstrap import ROOT

import tbt.models.ensemble as ensemble_module
from tbt.models.ensemble import TennisEnsemble
from tbt.models.feature_builder import FeatureBuilder
from tbt.models.metrics import evaluate_probabilities
from tbt.data.history_source import default_history_dir, load_training_history
from tbt.schemas import MatchRecord


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


EXPERIMENTAL_FEATURES = [
    "fatigue_3d_advantage",
    "fatigue_7d_advantage",
    "travel_km_advantage",
    "travel_known_both",
    "altitude_change_advantage",
    "altitude_known_both",
    "weather_temperature",
    "weather_humidity",
    "weather_wind",
    "weather_known",
    "environment_known",
]


# Promotion guardrails.
MIN_ENV_COVERAGE = 0.70
MIN_LOG_LOSS_IMPROVEMENT = 0.0001
MIN_BRIER_IMPROVEMENT = 0.00005
MIN_ROC_AUC_DELTA = 0.0
MIN_ACCURACY_DELTA = -0.001
MAX_ECE_WORSENING = 0.002


VARIANTS = {
    "baseline": {
        "features": [],
        "coverage_column": None,
    },
    "fatigue": {
        "features": [
            "fatigue_3d_advantage",
            "fatigue_7d_advantage",
        ],
        "coverage_column": None,
    },
    "travel": {
        "features": [
            "travel_km_advantage",
            "travel_known_both",
        ],
        "coverage_column": "travel_known_both",
    },
    "altitude": {
        "features": [
            "altitude_change_advantage",
            "altitude_known_both",
        ],
        "coverage_column": "altitude_known_both",
    },
    "weather": {
        "features": [
            "weather_temperature",
            "weather_humidity",
            "weather_wind",
            "weather_known",
        ],
        "coverage_column": "weather_known",
    },
    "environment_all": {
        "features": list(EXPERIMENTAL_FEATURES),
        "coverage_column": "environment_bundle_known",
    },
}


@dataclass
class ExperimentalPlayerState:
    recent_matches: deque = field(
        default_factory=lambda: deque(maxlen=100)
    )

    last_latitude: float | None = None
    last_longitude: float | None = None
    last_altitude: float | None = None


def _player_key(
    match: MatchRecord,
    first: bool,
) -> str:
    player_id = (
        match.player1_id
        if first
        else match.player2_id
    )

    return f"{match.tour.lower()}:{player_id}"


def _environment(
    match: MatchRecord,
) -> dict:
    payload = (
        match.provider_payload
        if isinstance(
            match.provider_payload,
            dict,
        )
        else {}
    )

    value = payload.get(
        "_tbt_environment"
    )

    return (
        value
        if isinstance(value, dict)
        else {}
    )


def _venue(
    env: dict,
) -> dict:
    value = env.get("venue")

    return (
        value
        if isinstance(value, dict)
        else {}
    )


def _weather(
    env: dict,
) -> dict:
    value = env.get("weather")

    return (
        value
        if isinstance(value, dict)
        else {}
    )


def _safe_float(
    value,
) -> float | None:
    try:
        if value is None:
            return None

        number = float(value)

        if not math.isfinite(number):
            return None

        return number

    except (
        TypeError,
        ValueError,
    ):
        return None


def _venue_altitude(
    venue: dict,
) -> float | None:
    value = _safe_float(
        venue.get("elevation_m")
    )

    if value is None:
        value = _safe_float(
            venue.get("altitude_m")
        )

    return value


def _haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    radius = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(
        lat2 - lat1
    )

    dlambda = math.radians(
        lon2 - lon1
    )

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(dlambda / 2.0) ** 2
    )

    return (
        2.0
        * radius
        * math.asin(
            math.sqrt(a)
        )
    )


def _recent_count(
    state: ExperimentalPlayerState,
    now,
    days: float,
) -> int:
    limit_seconds = (
        days * 86400.0
    )

    return sum(
        1
        for played_at
        in state.recent_matches
        if (
            0.0
            <= (
                now - played_at
            ).total_seconds()
            <= limit_seconds
        )
    )


def build_experimental_frame(
    matches: list[MatchRecord],
) -> pd.DataFrame:
    states: dict[
        str,
        ExperimentalPlayerState,
    ] = defaultdict(
        ExperimentalPlayerState
    )

    rows: list[dict] = []

    completed = sorted(
        (
            match
            for match in matches
            if match.is_completed
        ),
        key=lambda match: (
            match.event_date,
            match.match_id,
        ),
    )

    current_date = None
    batch: list[
        MatchRecord
    ] = []

    def process_batch(
        day_matches: list[
            MatchRecord
        ],
    ) -> None:
        # Snapshot celeho dna pred update player state.
        for original in day_matches:
            oriented, _ = (
                FeatureBuilder
                .orient_for_training(
                    original
                )
            )

            p1 = states[
                _player_key(
                    oriented,
                    True,
                )
            ]

            p2 = states[
                _player_key(
                    oriented,
                    False,
                )
            ]

            fatigue_3d = float(
                _recent_count(
                    p2,
                    oriented.scheduled_at,
                    3.0,
                )
                - _recent_count(
                    p1,
                    oriented.scheduled_at,
                    3.0,
                )
            )

            fatigue_7d = float(
                _recent_count(
                    p2,
                    oriented.scheduled_at,
                    7.0,
                )
                - _recent_count(
                    p1,
                    oriented.scheduled_at,
                    7.0,
                )
            )

            env = _environment(
                oriented
            )

            venue = _venue(
                env
            )

            weather = _weather(
                env
            )

            latitude = _safe_float(
                venue.get(
                    "latitude"
                )
            )

            longitude = _safe_float(
                venue.get(
                    "longitude"
                )
            )

            altitude = (
                _venue_altitude(
                    venue
                )
            )

            environment_known = float(
                env.get(
                    "venue_resolved"
                )
                is True
                and latitude
                is not None
                and longitude
                is not None
            )

            travel_known_both = float(
                environment_known
                and p1.last_latitude
                is not None
                and p1.last_longitude
                is not None
                and p2.last_latitude
                is not None
                and p2.last_longitude
                is not None
            )

            travel1 = 0.0
            travel2 = 0.0

            if travel_known_both:
                travel1 = (
                    _haversine_km(
                        p1.last_latitude,
                        p1.last_longitude,
                        latitude,
                        longitude,
                    )
                )

                travel2 = (
                    _haversine_km(
                        p2.last_latitude,
                        p2.last_longitude,
                        latitude,
                        longitude,
                    )
                )

            altitude_known_both = (
                float(
                    altitude
                    is not None
                    and p1.last_altitude
                    is not None
                    and p2.last_altitude
                    is not None
                )
            )

            altitude_change1 = 0.0
            altitude_change2 = 0.0

            if altitude_known_both:
                altitude_change1 = abs(
                    altitude
                    - p1.last_altitude
                )

                altitude_change2 = abs(
                    altitude
                    - p2.last_altitude
                )

            temperature = (
                _safe_float(
                    weather.get(
                        "temperature_2m"
                    )
                )
            )

            humidity = (
                _safe_float(
                    weather.get(
                        "relative_humidity_2m"
                    )
                )
            )

            wind = (
                _safe_float(
                    weather.get(
                        "wind_speed_10m"
                    )
                )
            )

            weather_known = float(
                temperature
                is not None
                and humidity
                is not None
                and wind
                is not None
            )

            environment_bundle_known = (
                float(
                    travel_known_both
                    and altitude_known_both
                    and weather_known
                )
            )

            rows.append(
                {
                    "match_id": (
                        original.match_id
                    ),
                    "fatigue_3d_advantage": (
                        fatigue_3d
                    ),
                    "fatigue_7d_advantage": (
                        fatigue_7d
                    ),
                    "travel_km_advantage": float(
                        np.clip(
                            (
                                travel2
                                - travel1
                            )
                            / 5000.0,
                            -2.0,
                            2.0,
                        )
                    ),
                    "travel_known_both": (
                        travel_known_both
                    ),
                    "altitude_change_advantage": float(
                        np.clip(
                            (
                                altitude_change2
                                - altitude_change1
                            )
                            / 2000.0,
                            -2.0,
                            2.0,
                        )
                    ),
                    "altitude_known_both": (
                        altitude_known_both
                    ),
                    "weather_temperature": (
                        temperature
                        / 40.0
                        if temperature
                        is not None
                        else 0.0
                    ),
                    "weather_humidity": (
                        humidity
                        / 100.0
                        if humidity
                        is not None
                        else 0.0
                    ),
                    "weather_wind": (
                        wind
                        / 50.0
                        if wind
                        is not None
                        else 0.0
                    ),
                    "weather_known": (
                        weather_known
                    ),
                    "environment_known": (
                        environment_known
                    ),
                    "environment_bundle_known": (
                        environment_bundle_known
                    ),
                }
            )

        # Update az po snapshotovani celeho dna.
        for original in day_matches:
            env = _environment(
                original
            )

            venue = _venue(
                env
            )

            latitude = _safe_float(
                venue.get(
                    "latitude"
                )
            )

            longitude = _safe_float(
                venue.get(
                    "longitude"
                )
            )

            altitude = (
                _venue_altitude(
                    venue
                )
            )

            for first in (
                True,
                False,
            ):
                state = states[
                    _player_key(
                        original,
                        first,
                    )
                ]

                state.recent_matches.append(
                    original.scheduled_at
                )

                if (
                    latitude
                    is not None
                    and longitude
                    is not None
                ):
                    state.last_latitude = (
                        latitude
                    )

                    state.last_longitude = (
                        longitude
                    )

                if altitude is not None:
                    state.last_altitude = (
                        altitude
                    )

    for match in completed:
        if current_date is None:
            current_date = (
                match.event_date
            )

        if (
            match.event_date
            != current_date
        ):
            process_batch(
                batch
            )

            batch = []

            current_date = (
                match.event_date
            )

        batch.append(
            match
        )

    if batch:
        process_batch(
            batch
        )

    return pd.DataFrame(
        rows
    )


def _fit_variant(
    train: pd.DataFrame,
    calibration: pd.DataFrame,
    test: pd.DataFrame,
    feature_names: list[str],
) -> np.ndarray:
    original_features = getattr(
        ensemble_module,
        "FEATURE_NAMES",
        None,
    )

    try:
        ensemble_module.FEATURE_NAMES = (
            list(
                feature_names
            )
        )

        model = (
            TennisEnsemble()
            .fit(
                train,
                calibration,
            )
        )

        return (
            model.predict_proba(
                test
            )
        )

    finally:
        if (
            original_features
            is not None
        ):
            ensemble_module.FEATURE_NAMES = (
                original_features
            )


def _coverage(
    frame: pd.DataFrame,
    column: str | None,
) -> float:
    if column is None:
        return 1.0

    if (
        column
        not in frame.columns
        or frame.empty
    ):
        return 0.0

    values = (
        pd.to_numeric(
            frame[column],
            errors="coerce",
        )
        .fillna(0.0)
    )

    return float(
        (
            values > 0.5
        ).mean()
    )


def _metric_delta(
    metrics: dict,
    baseline: dict,
) -> dict:
    return {
        "accuracy": (
            metrics["accuracy"]
            - baseline["accuracy"]
        ),
        "roc_auc": (
            metrics["roc_auc"]
            - baseline["roc_auc"]
        ),
        "log_loss": (
            metrics["log_loss"]
            - baseline["log_loss"]
        ),
        "brier_score": (
            metrics["brier_score"]
            - baseline[
                "brier_score"
            ]
        ),
        "ece_10": (
            metrics["ece_10"]
            - baseline["ece_10"]
        ),
    }


def _promotion_decision(
    name: str,
    delta: dict,
    coverage: dict,
) -> tuple[
    bool,
    list[str],
]:
    reasons: list[str] = []

    if name in {
        "travel",
        "altitude",
        "weather",
        "environment_all",
    }:
        minimum_coverage = min(
            coverage.get(
                "train",
                0.0,
            ),
            coverage.get(
                "calibration",
                0.0,
            ),
            coverage.get(
                "test",
                0.0,
            ),
        )

        if (
            minimum_coverage
            < MIN_ENV_COVERAGE
        ):
            reasons.append(
                "coverage "
                f"{minimum_coverage:.3f} "
                "< "
                f"{MIN_ENV_COVERAGE:.3f}"
            )

    if (
        delta["log_loss"]
        > -MIN_LOG_LOSS_IMPROVEMENT
    ):
        reasons.append(
            "log_loss improvement "
            "below threshold "
            f"({delta['log_loss']:+.6f})"
        )

    if (
        delta["brier_score"]
        > -MIN_BRIER_IMPROVEMENT
    ):
        reasons.append(
            "brier improvement "
            "below threshold "
            f"({delta['brier_score']:+.6f})"
        )

    if (
        delta["roc_auc"]
        < MIN_ROC_AUC_DELTA
    ):
        reasons.append(
            "roc_auc declined "
            f"({delta['roc_auc']:+.6f})"
        )

    if (
        delta["accuracy"]
        < MIN_ACCURACY_DELTA
    ):
        reasons.append(
            "accuracy declined "
            "too much "
            f"({delta['accuracy']:+.6f})"
        )

    if (
        delta["ece_10"]
        > MAX_ECE_WORSENING
    ):
        reasons.append(
            "ECE worsened "
            "too much "
            f"({delta['ece_10']:+.6f})"
        )

    return (
        not reasons,
        reasons,
    )


def main() -> None:
    matches = load_training_history(default_history_dir(ROOT), root=ROOT)

    print(
        f"Loaded {len(matches)} "
        "canonical completed matches"
    )

    base = (
        FeatureBuilder()
        .build_training_frame(
            matches
        )
    )

    if base.empty:
        raise SystemExit(
            "FeatureBuilder returned "
            "no training rows"
        )

    missing_base = [
        column
        for column
        in BASE_FEATURES
        if column
        not in base.columns
    ]

    if missing_base:
        raise SystemExit(
            "Baseline feature columns "
            "missing from FeatureBuilder: "
            + ", ".join(
                missing_base
            )
        )

    experimental = (
        build_experimental_frame(
            matches
        )
    )

    if experimental.empty:
        raise SystemExit(
            "Experimental feature "
            "builder returned no rows"
        )

    # Experimenty vzdy berieme z challenger buildera,
    # aby nevznikali *_x / *_y konflikty.
    base = base.drop(
        columns=(
            EXPERIMENTAL_FEATURES
            + [
                "environment_bundle_known"
            ]
        ),
        errors="ignore",
    )

    frame = base.merge(
        experimental,
        on="match_id",
        how="left",
        validate="one_to_one",
    )

    numeric_columns = (
        EXPERIMENTAL_FEATURES
        + [
            "environment_bundle_known"
        ]
    )

    for column in numeric_columns:
        if (
            column
            not in frame.columns
        ):
            frame[column] = 0.0

        frame[column] = (
            pd.to_numeric(
                frame[column],
                errors="coerce",
            )
            .fillna(0.0)
            .astype(float)
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

    frame["year"] = (
        pd.to_datetime(
            frame[
                "scheduled_at"
            ],
            utc=True,
        )
        .dt.year
    )

    years = sorted(
        int(year)
        for year
        in frame[
            "year"
        ].unique()
    )

    if not years:
        raise SystemExit(
            "No years available "
            "for challenger backtest"
        )

    first_test_year = max(
        years[0] + 2,
        years[-1] - 3,
    )

    print(
        f"Base features: "
        f"{len(BASE_FEATURES)}"
    )

    print(
        "Environment coverage overall: "
        f"venue="
        f"{_coverage(frame, 'environment_known'):.3f}, "
        f"travel="
        f"{_coverage(frame, 'travel_known_both'):.3f}, "
        f"altitude="
        f"{_coverage(frame, 'altitude_known_both'):.3f}, "
        f"weather="
        f"{_coverage(frame, 'weather_known'):.3f}, "
        f"bundle="
        f"{_coverage(frame, 'environment_bundle_known'):.3f}"
    )

    results = {
        name: {
            "folds": [],
            "y": [],
            "p": [],
            "coverage": [],
            "skipped_folds": [],
        }
        for name
        in VARIANTS
    }

    for year in [
        value
        for value in years
        if (
            value
            >= first_test_year
        )
    ]:
        historical = frame[
            frame["year"] < year
        ].copy()

        test = frame[
            frame["year"] == year
        ].copy()

        if (
            len(historical) < 1200
            or len(test) < 100
        ):
            continue

        historical = (
            historical.sort_values(
                [
                    "scheduled_at",
                    "match_id",
                ]
            )
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

        train = (
            historical.iloc[
                :split
            ].copy()
        )

        calibration = (
            historical.iloc[
                split:
            ].copy()
        )

        print(
            f"Fold {year}: "
            f"train={len(train)}, "
            f"calibration="
            f"{len(calibration)}, "
            f"test={len(test)}"
        )

        for (
            variant_name,
            config,
        ) in VARIANTS.items():
            coverage_column = (
                config[
                    "coverage_column"
                ]
            )

            coverage = {
                "train": _coverage(
                    train,
                    coverage_column,
                ),
                "calibration": _coverage(
                    calibration,
                    coverage_column,
                ),
                "test": _coverage(
                    test,
                    coverage_column,
                ),
            }

            requires_environment = (
                coverage_column
                is not None
            )

            if (
                requires_environment
                and min(
                    coverage.values()
                )
                < MIN_ENV_COVERAGE
            ):
                results[
                    variant_name
                ][
                    "skipped_folds"
                ].append(
                    {
                        "year": int(
                            year
                        ),
                        "reason": (
                            "insufficient_"
                            "environment_"
                            "coverage"
                        ),
                        "coverage": (
                            coverage
                        ),
                    }
                )

                print(
                    f"  {variant_name}: "
                    "skipped, coverage="
                    f"{coverage['train']:.3f}/"
                    f"{coverage['calibration']:.3f}/"
                    f"{coverage['test']:.3f}"
                )

                continue

            feature_names = (
                list(
                    BASE_FEATURES
                )
                + list(
                    config[
                        "features"
                    ]
                )
            )

            probabilities = (
                _fit_variant(
                    train,
                    calibration,
                    test,
                    feature_names,
                )
            )

            metrics = (
                evaluate_probabilities(
                    test[
                        "target"
                    ],
                    probabilities,
                )
            )

            results[
                variant_name
            ][
                "folds"
            ].append(
                {
                    "year": int(
                        year
                    ),
                    "train_rows": int(
                        len(train)
                    ),
                    "calibration_rows": int(
                        len(
                            calibration
                        )
                    ),
                    "test_rows": int(
                        len(test)
                    ),
                    "coverage": (
                        coverage
                    ),
                    "metrics": (
                        metrics
                    ),
                }
            )

            results[
                variant_name
            ][
                "coverage"
            ].append(
                coverage
            )

            results[
                variant_name
            ][
                "y"
            ].extend(
                test[
                    "target"
                ]
                .astype(int)
                .tolist()
            )

            results[
                variant_name
            ][
                "p"
            ].extend(
                probabilities.tolist()
            )

    if not results[
        "baseline"
    ][
        "y"
    ]:
        raise SystemExit(
            "Not enough history "
            "to create challenger folds"
        )

    report = {
        "method": (
            "calendar-year "
            "walk-forward challenger "
            "test; every test year "
            "is strictly later than "
            "training/calibration"
        ),
        "first_test_year": int(
            first_test_year
        ),
        "canonical_matches": int(
            len(matches)
        ),
        "coverage": {
            "environment_known": (
                _coverage(
                    frame,
                    "environment_known",
                )
            ),
            "travel_known_both": (
                _coverage(
                    frame,
                    "travel_known_both",
                )
            ),
            "altitude_known_both": (
                _coverage(
                    frame,
                    "altitude_known_both",
                )
            ),
            "weather_known": (
                _coverage(
                    frame,
                    "weather_known",
                )
            ),
            "environment_bundle_known": (
                _coverage(
                    frame,
                    "environment_bundle_known",
                )
            ),
        },
        "guardrails": {
            "min_environment_coverage": (
                MIN_ENV_COVERAGE
            ),
            "min_log_loss_improvement": (
                MIN_LOG_LOSS_IMPROVEMENT
            ),
            "min_brier_improvement": (
                MIN_BRIER_IMPROVEMENT
            ),
            "min_roc_auc_delta": (
                MIN_ROC_AUC_DELTA
            ),
            "min_accuracy_delta": (
                MIN_ACCURACY_DELTA
            ),
            "max_ece_worsening": (
                MAX_ECE_WORSENING
            ),
        },
        "variants": {},
    }

    for (
        variant_name,
        result,
    ) in results.items():
        if result["y"]:
            overall = (
                evaluate_probabilities(
                    result["y"],
                    result["p"],
                )
            )
        else:
            overall = None

        report[
            "variants"
        ][
            variant_name
        ] = {
            "overall": overall,
            "folds": (
                result["folds"]
            ),
            "skipped_folds": (
                result[
                    "skipped_folds"
                ]
            ),
        }

    baseline_metrics = (
        report[
            "variants"
        ][
            "baseline"
        ][
            "overall"
        ]
    )

    if baseline_metrics is None:
        raise SystemExit(
            "Baseline metrics "
            "are unavailable"
        )

    promotion_candidates: list[
        str
    ] = []

    for (
        variant_name,
        result,
    ) in (
        report[
            "variants"
        ].items()
    ):
        if (
            variant_name
            == "baseline"
        ):
            result[
                "delta_vs_baseline"
            ] = {
                "accuracy": 0.0,
                "roc_auc": 0.0,
                "log_loss": 0.0,
                "brier_score": 0.0,
                "ece_10": 0.0,
            }

            result[
                "promotion"
            ] = {
                "eligible": False,
                "reasons": [
                    "baseline"
                ],
            }

            continue

        metrics = result[
            "overall"
        ]

        if metrics is None:
            result[
                "delta_vs_baseline"
            ] = None

            result[
                "promotion"
            ] = {
                "eligible": False,
                "reasons": [
                    "no_valid_fold"
                ],
            }

            continue

        delta = _metric_delta(
            metrics,
            baseline_metrics,
        )

        result[
            "delta_vs_baseline"
        ] = delta

        coverage_column = (
            VARIANTS[
                variant_name
            ][
                "coverage_column"
            ]
        )

        fold_coverage = (
            results[
                variant_name
            ][
                "coverage"
            ]
        )

        if coverage_column is None:
            aggregate_coverage = {
                "train": 1.0,
                "calibration": 1.0,
                "test": 1.0,
            }

        elif fold_coverage:
            aggregate_coverage = {
                split_name: float(
                    min(
                        item[
                            split_name
                        ]
                        for item
                        in fold_coverage
                    )
                )
                for split_name
                in (
                    "train",
                    "calibration",
                    "test",
                )
            }

        else:
            aggregate_coverage = {
                "train": 0.0,
                "calibration": 0.0,
                "test": 0.0,
            }

        eligible, reasons = (
            _promotion_decision(
                variant_name,
                delta,
                aggregate_coverage,
            )
        )

        result[
            "promotion"
        ] = {
            "eligible": (
                eligible
            ),
            "coverage": (
                aggregate_coverage
            ),
            "reasons": (
                reasons
            ),
        }

        if eligible:
            promotion_candidates.append(
                variant_name
            )

    report[
        "promotion_candidates"
    ] = promotion_candidates

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
