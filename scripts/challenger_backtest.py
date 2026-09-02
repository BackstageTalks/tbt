from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from _bootstrap import ROOT

import tbt.models.ensemble as ensemble_module
from tbt.models.ensemble import TennisEnsemble
from tbt.models.feature_builder import FEATURE_NAMES, FeatureBuilder
from tbt.models.metrics import evaluate_probabilities
from tbt.repositories.supabase import SupabaseRepository
from tbt.schemas import MatchRecord


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
    ],
    "altitude": [
        "altitude_change_advantage",
    ],
    "weather": [
        "weather_temperature",
        "weather_humidity",
        "weather_wind",
        "environment_known",
    ],
    "environment_all": EXPERIMENTAL_FEATURES,
}


@dataclass
class ExperimentalPlayerState:
    recent_matches: deque = field(
        default_factory=lambda: deque(maxlen=100)
    )
    last_latitude: float | None = None
    last_longitude: float | None = None
    last_altitude: float | None = None


def player_key(match: MatchRecord, first: bool) -> str:
    pid = match.player1_id if first else match.player2_id
    return f"{match.tour.lower()}:{pid}"


def environment(match: MatchRecord) -> dict:
    payload = (
        match.provider_payload
        if isinstance(match.provider_payload, dict)
        else {}
    )

    env = payload.get("_tbt_environment")

    return env if isinstance(env, dict) else {}


def venue(env: dict) -> dict:
    value = env.get("venue")
    return value if isinstance(value, dict) else {}


def weather(env: dict) -> dict:
    value = env.get("weather")
    return value if isinstance(value, dict) else {}


def haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    r = 6371.0088

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

    return 2.0 * r * math.asin(math.sqrt(a))


def recent_count(
    state: ExperimentalPlayerState,
    now,
    days: float,
) -> int:
    threshold = days * 86400.0

    return sum(
        1
        for played_at in state.recent_matches
        if 0.0
        <= (now - played_at).total_seconds()
        <= threshold
    )


def safe_float(value) -> float | None:
    try:
        if value is None:
            return None

        number = float(value)

        if not math.isfinite(number):
            return None

        return number

    except (TypeError, ValueError):
        return None


def build_experimental_features(
    matches: list[MatchRecord],
) -> pd.DataFrame:
    states: dict[str, ExperimentalPlayerState] = defaultdict(
        ExperimentalPlayerState
    )

    rows = []

    completed = sorted(
        (m for m in matches if m.is_completed),
        key=lambda m: (m.event_date, m.match_id),
    )

    current_date = None
    batch: list[MatchRecord] = []

    def process_batch(day_matches: list[MatchRecord]) -> None:
        for original in day_matches:
            oriented, _ = FeatureBuilder.orient_for_training(
                original
            )

            p1 = states[player_key(oriented, True)]
            p2 = states[player_key(oriented, False)]

            f3_1 = recent_count(
                p1,
                oriented.scheduled_at,
                3.0,
            )
            f3_2 = recent_count(
                p2,
                oriented.scheduled_at,
                3.0,
            )

            f7_1 = recent_count(
                p1,
                oriented.scheduled_at,
                7.0,
            )
            f7_2 = recent_count(
                p2,
                oriented.scheduled_at,
                7.0,
            )

            env = environment(oriented)
            v = venue(env)
            w = weather(env)

            lat = safe_float(v.get("latitude"))
            lon = safe_float(v.get("longitude"))
            altitude = safe_float(v.get("elevation_m"))

            env_known = float(
                env.get("venue_resolved") is True
                and lat is not None
                and lon is not None
            )

            travel1 = 0.0
            travel2 = 0.0

            if (
                env_known
                and p1.last_latitude is not None
                and p1.last_longitude is not None
            ):
                travel1 = haversine_km(
                    p1.last_latitude,
                    p1.last_longitude,
                    lat,
                    lon,
                )

            if (
                env_known
                and p2.last_latitude is not None
                and p2.last_longitude is not None
            ):
                travel2 = haversine_km(
                    p2.last_latitude,
                    p2.last_longitude,
                    lat,
                    lon,
                )

            altitude_change1 = 0.0
            altitude_change2 = 0.0

            if (
                altitude is not None
                and p1.last_altitude is not None
            ):
                altitude_change1 = abs(
                    altitude - p1.last_altitude
                )

            if (
                altitude is not None
                and p2.last_altitude is not None
            ):
                altitude_change2 = abs(
                    altitude - p2.last_altitude
                )

            temperature = safe_float(
                w.get("temperature_2m")
            )
            humidity = safe_float(
                w.get("relative_humidity_2m")
            )
            wind = safe_float(
                w.get("wind_speed_10m")
            )

            rows.append(
                {
                    "match_id": original.match_id,
                    "fatigue_3d_advantage": float(
                        f3_2 - f3_1
                    ),
                    "fatigue_7d_advantage": float(
                        f7_2 - f7_1
                    ),
                    "travel_km_advantage": float(
                        np.clip(
                            (travel2 - travel1) / 5000.0,
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
                    "environment_known": env_known,
                }
            )

        for original in day_matches:
            env = environment(original)
            v = venue(env)

            lat = safe_float(v.get("latitude"))
            lon = safe_float(v.get("longitude"))
            altitude = safe_float(v.get("elevation_m"))

            for first in (True, False):
                state = states[player_key(original, first)]

                state.recent_matches.append(
                    original.scheduled_at
                )

                if lat is not None and lon is not None:
                    state.last_latitude = lat
                    state.last_longitude = lon

                if altitude is not None:
                    state.last_altitude = altitude

    for match in completed:
        if current_date is None:
            current_date = match.event_date

        if match.event_date != current_date:
            process_batch(batch)
            batch = []
            current_date = match.event_date

        batch.append(match)

    if batch:
        process_batch(batch)

    return pd.DataFrame(rows)


def fit_variant(
    train: pd.DataFrame,
    calibration: pd.DataFrame,
    test: pd.DataFrame,
    feature_names: list[str],
) -> np.ndarray:
    original_module_features = getattr(
        ensemble_module,
        "FEATURE_NAMES",
        None,
    )

    try:
        ensemble_module.FEATURE_NAMES = feature_names

        model = TennisEnsemble().fit(
            train,
            calibration,
        )

        return model.predict_proba(test)

    finally:
        if original_module_features is not None:
            ensemble_module.FEATURE_NAMES = (
                original_module_features
            )


def main() -> None:
    repo = SupabaseRepository()

    matches = repo.get_completed_matches()

    print(
        f"Loaded {len(matches)} canonical completed matches"
    )

    base = FeatureBuilder().build_training_frame(
        matches
    )

    experimental = build_experimental_features(
        matches
    )

    frame = base.merge(
        experimental,
        on="match_id",
        how="left",
        validate="one_to_one",
    )

    for column in EXPERIMENTAL_FEATURES:
        frame[column] = (
            pd.to_numeric(
                frame[column],
                errors="coerce",
            )
            .fillna(0.0)
            .astype(float)
        )

    frame = frame.sort_values(
        ["scheduled_at", "match_id"]
    ).reset_index(drop=True)

    frame["year"] = pd.to_datetime(
        frame["scheduled_at"],
        utc=True,
    ).dt.year

    years = sorted(
        int(y)
        for y in frame["year"].unique()
    )

    first_test_year = max(
        years[0] + 2,
        years[-1] - 3,
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
        y
        for y in years
        if y >= first_test_year
    ]:
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
            "scheduled_at"
        )

        split = max(
            300,
            int(len(historical) * 0.85),
        )

        split = min(
            split,
            len(historical) - 120,
        )

        train = historical.iloc[:split].copy()
        calibration = historical.iloc[split:].copy()

        for name, extra_features in VARIANTS.items():
            feature_names = (
                list(FEATURE_NAMES)
                + list(extra_features)
            )

            p = fit_variant(
                train,
                calibration,
                test,
                feature_names,
            )

            metrics = evaluate_probabilities(
                test["target"],
                p,
            )

            results[name]["folds"].append(
                {
                    "year": year,
                    "train_rows": int(len(train)),
                    "calibration_rows": int(
                        len(calibration)
                    ),
                    "test_rows": int(len(test)),
                    "metrics": metrics,
                }
            )

            results[name]["y"].extend(
                test["target"]
                .astype(int)
                .tolist()
            )

            results[name]["p"].extend(
                p.tolist()
            )

    report = {
        "method": (
            "calendar-year walk-forward challenger test; "
            "all test matches strictly later than "
            "training/calibration"
        ),
        "first_test_year": first_test_year,
        "environment_coverage": float(
            frame["environment_known"].mean()
        ),
        "variants": {},
    }

    for name, result in results.items():
        overall = evaluate_probabilities(
            result["y"],
            result["p"],
        )

        report["variants"][name] = {
            "overall": overall,
            "folds": result["folds"],
        }

    baseline = report["variants"]["baseline"][
        "overall"
    ]

    for name, result in report["variants"].items():
        metrics = result["overall"]

        result["delta_vs_baseline"] = {
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

    candidates = []

    for name, result in report["variants"].items():
        if name == "baseline":
            continue

        delta = result["delta_vs_baseline"]

        if (
            delta["log_loss"] < 0
            and delta["brier_score"] < 0
            and delta["roc_auc"] >= -0.001
        ):
            candidates.append(name)

    report["promotion_candidates"] = candidates

    path = ROOT / "reports" / "challenger_backtest.json"

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
