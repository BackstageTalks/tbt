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
from tbt.repositories.supabase import SupabaseRepository
from tbt.schemas import MatchRecord


# Frozen champion feature set.
# Baseline sa nesmie automaticky meniť podľa experimentov vo FeatureBuilder.
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
    "altitude_change_advantage",
    "weather_temperature",
    "weather_humidity",
    "weather_wind",
    "environment_known",
]


VARIANTS = {
    "baseline": [],
    "fatigue": [
        "fatigue_3d_advantage",
        "fatigue_7d_advantage",
    ],
    "travel": [
        "travel_km_advantage",
        "environment_known",
    ],
    "altitude": [
        "altitude_change_advantage",
        "environment_known",
    ],
    "weather": [
        "weather_temperature",
        "weather_humidity",
        "weather_wind",
        "environment_known",
    ],
    "environment_all": list(EXPERIMENTAL_FEATURES),
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
        if isinstance(match.provider_payload, dict)
        else {}
    )

    value = payload.get("_tbt_environment")

    return value if isinstance(value, dict) else {}


def _venue(
    env: dict,
) -> dict:
    value = env.get("venue")

    return value if isinstance(value, dict) else {}


def _weather(
    env: dict,
) -> dict:
    value = env.get("weather")

    return value if isinstance(value, dict) else {}


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

    except (TypeError, ValueError):
        return None


def _haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    radius = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(dlambda / 2.0) ** 2
    )

    return (
        2.0
        * radius
        * math.asin(math.sqrt(a))
    )


def _recent_count(
    state: ExperimentalPlayerState,
    now,
    days: float,
) -> int:
    limit_seconds = days * 86400.0

    return sum(
        1
        for played_at in state.recent_matches
        if (
            0.0
            <= (now - played_at).total_seconds()
            <= limit_seconds
        )
    )


def build_experimental_frame(
    matches: list[MatchRecord],
) -> pd.DataFrame:
    """
    Challenger-only feature builder.

    Rovnako ako production FeatureBuilder:
    všetky zápasy v jednom kalendárnom dni sa najprv
    snapshotnú a až potom sa aktualizuje player state.
    """

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
    batch: list[MatchRecord] = []

    def process_batch(
        day_matches: list[MatchRecord],
    ) -> None:
        # SNAPSHOT
        for original in day_matches:
            oriented, _ = (
                FeatureBuilder.orient_for_training(
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

            env = _environment(oriented)
            venue = _venue(env)
            weather = _weather(env)

            latitude = _safe_float(
                venue.get("latitude")
            )

            longitude = _safe_float(
                venue.get("longitude")
            )

            altitude = _safe_float(
                venue.get("elevation_m")
            )

            environment_known = float(
                env.get("venue_resolved") is True
                and latitude is not None
                and longitude is not None
            )

            travel1 = 0.0
            travel2 = 0.0

            if (
                environment_known
                and p1.last_latitude is not None
                and p1.last_longitude is not None
            ):
                travel1 = _haversine_km(
                    p1.last_latitude,
                    p1.last_longitude,
                    latitude,
                    longitude,
                )

            if (
                environment_known
                and p2.last_latitude is not None
                and p2.last_longitude is not None
            ):
                travel2 = _haversine_km(
                    p2.last_latitude,
                    p2.last_longitude,
                    latitude,
                    longitude,
                )

            altitude_change1 = 0.0
            altitude_change2 = 0.0

            if (
                altitude is not None
                and p1.last_altitude is not None
            ):
                altitude_change1 = abs(
                    altitude
                    - p1.last_altitude
                )

            if (
                altitude is not None
                and p2.last_altitude is not None
            ):
                altitude_change2 = abs(
                    altitude
                    - p2.last_altitude
                )

            temperature = _safe_float(
                weather.get("temperature_2m")
            )

            humidity = _safe_float(
                weather.get(
                    "relative_humidity_2m"
                )
            )

            wind = _safe_float(
                weather.get("wind_speed_10m")
            )

            rows.append(
                {
                    "match_id": original.match_id,
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
                    "weather_temperature": (
                        temperature / 40.0
                        if temperature is not None
                        else 0.0
                    ),
                    "weather_humidity": (
                        humidity / 100.0
                        if humidity is not None
                        else 0.0
                    ),
                    "weather_wind": (
                        wind / 50.0
                        if wind is not None
                        else 0.0
                    ),
                    "environment_known": (
                        environment_known
                    ),
                }
            )

        # UPDATE až po celom dennom batchi
        for original in day_matches:
            env = _environment(original)
            venue = _venue(env)

            latitude = _safe_float(
                venue.get("latitude")
            )

            longitude = _safe_float(
                venue.get("longitude")
            )

            altitude = _safe_float(
                venue.get("elevation_m")
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
                    latitude is not None
                    and longitude is not None
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
            process_batch(batch)

            batch = []

            current_date = (
                match.event_date
            )

        batch.append(match)

    if batch:
        process_batch(batch)

    return pd.DataFrame(rows)


def _fit_variant(
    train: pd.DataFrame,
    calibration: pd.DataFrame,
    test: pd.DataFrame,
    feature_names: list[str],
) -> np.ndarray:
    """
    TennisEnsemble používa FEATURE_NAMES importované
    na module-level.

    Preto ich dočasne prepíšeme iba počas jedného
    experimentálneho fitu a potom ich okamžite obnovíme.
    """

    original_features = getattr(
        ensemble_module,
        "FEATURE_NAMES",
        None,
    )

    try:
        ensemble_module.FEATURE_NAMES = (
            list(feature_names)
        )

        model = TennisEnsemble().fit(
            train,
            calibration,
        )

        probabilities = (
            model.predict_proba(test)
        )

        return probabilities

    finally:
        if original_features is not None:
            ensemble_module.FEATURE_NAMES = (
                original_features
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
            - baseline["brier_score"]
        ),
        "ece_10": (
            metrics["ece_10"]
            - baseline["ece_10"]
        ),
    }


def main() -> None:
    repo = SupabaseRepository()

    matches = (
        repo.get_completed_matches()
    )

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

    experimental = (
        build_experimental_frame(
            matches
        )
    )

    if experimental.empty:
        raise SystemExit(
            "Experimental feature builder "
            "returned no rows"
        )

    # Dôležité:
    # ak FeatureBuilder už niektorý experimentálny
    # feature obsahuje, nemergujeme ho druhýkrát.
    # Inak pandas vytvorí *_x / *_y a pôvodný názov zmizne.
    missing_experimental = [
        column
        for column in EXPERIMENTAL_FEATURES
        if column not in base.columns
    ]

    merge_columns = (
        ["match_id"]
        + missing_experimental
    )

    frame = base.merge(
        experimental[
            merge_columns
        ],
        on="match_id",
        how="left",
        validate="one_to_one",
    )

    # Garantujeme existenciu všetkých challenger columns.
    for column in (
        EXPERIMENTAL_FEATURES
    ):
        if column not in frame.columns:
            frame[column] = 0.0

        frame[column] = (
            pd.to_numeric(
                frame[column],
                errors="coerce",
            )
            .fillna(0.0)
            .astype(float)
        )

    missing_base = [
        column
        for column in BASE_FEATURES
        if column not in frame.columns
    ]

    if missing_base:
        raise SystemExit(
            "Baseline feature columns "
            "missing from FeatureBuilder: "
            + ", ".join(
                missing_base
            )
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
        for year in (
            frame["year"].unique()
        )
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

    existing_experimental = sorted(
        set(
            EXPERIMENTAL_FEATURES
        ).intersection(
            base.columns
        )
    )

    print(
        f"Base features: "
        f"{len(BASE_FEATURES)}"
    )

    print(
        "Experimental already in "
        "FeatureBuilder: "
        f"{existing_experimental}"
    )

    print(
        "Experimental derived by "
        "challenger: "
        f"{missing_experimental}"
    )

    results = {
        name: {
            "folds": [],
            "y": [],
            "p": [],
        }
        for name in VARIANTS
    }

    for year in [
        value
        for value in years
        if value >= first_test_year
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
            extras,
        ) in VARIANTS.items():
            feature_names = (
                list(BASE_FEATURES)
                + list(extras)
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
                    test["target"],
                    probabilities,
                )
            )

            results[
                variant_name
            ]["folds"].append(
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
                    "metrics": metrics,
                }
            )

            results[
                variant_name
            ]["y"].extend(
                test["target"]
                .astype(int)
                .tolist()
            )

            results[
                variant_name
            ]["p"].extend(
                probabilities.tolist()
            )

    if not results[
        "baseline"
    ]["y"]:
        raise SystemExit(
            "Not enough history "
            "to create challenger folds"
        )

    report = {
        "method": (
            "calendar-year walk-forward "
            "challenger test; every test "
            "year is strictly later than "
            "training/calibration"
        ),
        "first_test_year": int(
            first_test_year
        ),
        "canonical_matches": int(
            len(matches)
        ),
        "environment_coverage": float(
            (
                frame[
                    "environment_known"
                ]
                > 0.5
            ).mean()
        ),
        "variants": {},
    }

    for (
        variant_name,
        result,
    ) in results.items():
        overall = (
            evaluate_probabilities(
                result["y"],
                result["p"],
            )
        )

        report[
            "variants"
        ][
            variant_name
        ] = {
            "overall": overall,
            "folds": result[
                "folds"
            ],
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

    for result in (
        report["variants"].values()
    ):
        result[
            "delta_vs_baseline"
        ] = _metric_delta(
            result["overall"],
            baseline_metrics,
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
            continue

        delta = result[
            "delta_vs_baseline"
        ]

        # Konzervatívny shortlist.
        # Produkčný promotion ešte nerobíme automaticky.
        if (
            delta["log_loss"] < 0.0
            and delta[
                "brier_score"
            ] < 0.0
            and delta[
                "roc_auc"
            ] >= -0.001
        ):
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
            default=str,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            report,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
