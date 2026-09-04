from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from _bootstrap import ROOT
from tbt.models.ensemble import TennisEnsemble
from tbt.models.feature_builder import FEATURE_NAMES, FeatureBuilder
from tbt.repositories.supabase import SupabaseRepository
from tbt.services.prime import prime_components


def _safe_historical_split(historical: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    ordered = historical.sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)
    if len(ordered) < 500:
        return None

    dates = pd.to_datetime(ordered["scheduled_at"], utc=True).dt.date
    cut_index = min(max(int(len(ordered) * 0.85), 300), len(ordered) - 120)
    cut_day = dates.iloc[cut_index]

    train = ordered[dates < cut_day].copy()
    calibration = ordered[dates >= cut_day].copy()
    if len(train) < 300 or len(calibration) < 120:
        return None
    if pd.to_datetime(train["scheduled_at"], utc=True).max() >= pd.to_datetime(calibration["scheduled_at"], utc=True).min():
        raise RuntimeError("Prime backtest train/calibration overlap")
    return train, calibration


def _reverse_feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Mirror player1/player2 feature orientation for production-style symmetry."""
    reverse = frame.copy()
    for name in FEATURE_NAMES:
        if name not in reverse.columns:
            continue
        if name == "elo_probability":
            reverse[name] = 1.0 - pd.to_numeric(reverse[name], errors="coerce").fillna(0.5)
        elif name.endswith("_diff") or name.endswith("_advantage") or name.endswith("_interaction"):
            reverse[name] = -pd.to_numeric(reverse[name], errors="coerce").fillna(0.0)
    return reverse


def _symmetric_probability(model: TennisEnsemble, frame: pd.DataFrame) -> np.ndarray:
    forward = np.asarray(model.predict_proba(frame), dtype=float)
    reverse = np.asarray(model.predict_proba(_reverse_feature_frame(frame)), dtype=float)
    return np.clip(0.5 * (forward + (1.0 - reverse)), 0.01, 0.99)


def _prime_row(source: pd.Series, p1: float) -> dict[str, Any]:
    p1 = float(np.clip(p1, 0.01, 0.99))
    p2 = 1.0 - p1
    p1_wins = p1 >= 0.5
    return {
        "player1_probability": p1,
        "player2_probability": p2,
        "predicted_winner_id": "p1" if p1_wins else "p2",
        "player1_id": "p1",
        "player2_id": "p2",
        "features": {name: float(source.get(name, 0.0) or 0.0) for name in FEATURE_NAMES},
    }


def _wilson(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    margin = z * math.sqrt((p * (1.0 - p) / n) + z * z / (4.0 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "n": 0,
            "accuracy": None,
            "accuracy_ci95": [None, None],
            "mean_model_probability": None,
            "mean_data_depth": None,
            "mean_factor_agreement": None,
        }
    successes = int(frame["correct"].sum())
    lo, hi = _wilson(successes, len(frame))
    return {
        "n": int(len(frame)),
        "correct": successes,
        "accuracy": float(frame["correct"].mean()),
        "accuracy_ci95": [lo, hi],
        "mean_model_probability": float(frame["winner_probability"].mean()),
        "mean_data_depth": float(frame["data_depth"].mean()),
        "mean_factor_agreement": float(frame["factor_agreement_pct"].mean() / 100.0),
    }


def _apply_weights(frame: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    work = frame.copy()
    work["prime_score"] = 100.0 * (
        weights["model_probability"] * work["probability_strength"]
        + weights["data_depth"] * work["data_depth"]
        + weights["factor_agreement"] * work["agreement_strength"]
    )
    return work


def _top_n(frame: pd.DataFrame, score_column: str, n: int) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    return (
        frame.sort_values(
            ["day", score_column, "winner_probability", "match_id"],
            ascending=[True, False, False, True],
        )
        .groupby("day", group_keys=False)
        .head(n)
        .copy()
    )


def _top_n_report(frame: pd.DataFrame, score_column: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for n in (1, 3, 5, 8, 10):
        chosen = _top_n(frame, score_column, n)
        stats = _summary(chosen)
        stats["days"] = int(chosen["day"].nunique()) if not chosen.empty else 0
        stats["mean_picks_per_day"] = float(len(chosen) / stats["days"]) if stats["days"] else 0.0
        result[str(n)] = stats
    return result


def _threshold_report(frame: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    total = len(frame)
    for threshold in (40, 45, 50, 55, 60, 65, 70, 75, 80, 85):
        subset = frame[frame["prime_score"] >= threshold]
        stats = _summary(subset)
        stats["coverage"] = float(len(subset) / total) if total else 0.0
        result[str(threshold)] = stats
    return result


def _candidate_weights() -> list[dict[str, float]]:
    candidates: list[dict[str, float]] = []
    steps = [x / 100.0 for x in range(0, 101, 5)]
    for probability_weight, depth_weight in itertools.product(steps, steps):
        agreement_weight = 1.0 - probability_weight - depth_weight
        if probability_weight < 0.50 or probability_weight > 0.90:
            continue
        if depth_weight > 0.35:
            continue
        if agreement_weight < -1e-9 or agreement_weight > 0.35:
            continue
        agreement_weight = max(0.0, agreement_weight)
        candidates.append(
            {
                "model_probability": round(probability_weight, 2),
                "data_depth": round(depth_weight, 2),
                "factor_agreement": round(agreement_weight, 2),
            }
        )
    return candidates


def _tune_weights(frame: pd.DataFrame, top_n: int) -> tuple[dict[str, float], list[dict[str, Any]]]:
    if frame.empty:
        raise ValueError("Cannot tune Prime weights on an empty frame")

    leaderboard: list[dict[str, Any]] = []
    for weights in _candidate_weights():
        scored = _apply_weights(frame, weights)
        chosen = _top_n(scored, "prime_score", top_n)
        top5 = _top_n(scored, "prime_score", 5)
        top3 = _top_n(scored, "prime_score", 3)
        accuracy = float(chosen["correct"].mean()) if len(chosen) else 0.0
        accuracy5 = float(top5["correct"].mean()) if len(top5) else 0.0
        accuracy3 = float(top3["correct"].mean()) if len(top3) else 0.0
        # Primary goal is the user's visible Prime shelf (top N/day).
        # Smaller shelves only break ties; probability weight then wins the final tie
        # to keep the selector conservative and close to the calibrated model.
        leaderboard.append(
            {
                "weights": weights,
                "top_n": top_n,
                "n": int(len(chosen)),
                "accuracy": accuracy,
                "top5_accuracy": accuracy5,
                "top3_accuracy": accuracy3,
            }
        )

    leaderboard.sort(
        key=lambda row: (
            -row["accuracy"],
            -row["top5_accuracy"],
            -row["top3_accuracy"],
            -row["weights"]["model_probability"],
            row["weights"]["data_depth"] + row["weights"]["factor_agreement"],
        )
    )
    return dict(leaderboard[0]["weights"]), leaderboard[:20]


def _score_year(
    frame: pd.DataFrame,
    year: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    historical = frame[frame["year"] < year].copy()
    test = frame[frame["year"] == year].copy()
    if len(historical) < 1200 or len(test) < 100:
        raise ValueError(
            f"Year {year} cannot be evaluated safely: historical={len(historical)}, test={len(test)}"
        )

    split = _safe_historical_split(historical)
    if split is None:
        raise ValueError(f"Year {year}: unable to create train/calibration split")
    train, calibration = split

    model = TennisEnsemble().fit(train, calibration)
    probabilities = _symmetric_probability(model, test)

    rows: list[dict[str, Any]] = []
    for idx, (_, source) in enumerate(test.iterrows()):
        p1 = float(probabilities[idx])
        components = prime_components(_prime_row(source, p1))
        target = int(source["target"])
        predicted = 1 if p1 >= 0.5 else 0
        rows.append(
            {
                "match_id": str(source["match_id"]),
                "scheduled_at": source["scheduled_at"],
                "day": pd.to_datetime(source["scheduled_at"], utc=True).date().isoformat(),
                "year": year,
                "tour": str(source.get("tour") or ""),
                "surface": str(source.get("surface") or "unknown"),
                "winner_probability": float(components["winner_probability"]),
                "probability_strength": float(components["model_probability_strength"]),
                "data_depth": float(components["data_depth"]),
                "factor_agreement_pct": float(components["factor_agreement_pct"]),
                "agreement_strength": float(components["factor_agreement_strength"]),
                "correct": int(predicted == target),
            }
        )

    scored = pd.DataFrame(rows)
    meta = {
        "year": year,
        "train_rows": int(len(train)),
        "calibration_rows": int(len(calibration)),
        "test_rows": int(len(test)),
        "model_version": model.version,
        "all_predictions": _summary(scored),
    }
    return scored, meta


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Tune BlinQ Prime ranking on one out-of-time year and validate it on a later untouched year"
        )
    )
    parser.add_argument("--tune-year", type=int, default=2025)
    parser.add_argument("--validation-year", type=int, default=2026)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--report", default=str(ROOT / "reports" / "prime_backtest.json"))
    args = parser.parse_args()

    if args.validation_year <= args.tune_year:
        raise SystemExit("validation-year must be later than tune-year")
    if args.top_n < 1 or args.top_n > 50:
        raise SystemExit("top-n must be between 1 and 50")

    matches = SupabaseRepository().get_completed_matches()
    print(f"Loaded {len(matches):,} canonical completed matches")

    frame = FeatureBuilder().build_training_frame(matches)
    if frame.empty:
        raise SystemExit("FeatureBuilder returned no training rows")

    frame = frame.sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)
    frame["year"] = pd.to_datetime(frame["scheduled_at"], utc=True).dt.year
    years = sorted(int(y) for y in frame["year"].unique())
    print(f"Available years: {years}")

    print(f"Building out-of-time tuning predictions for {args.tune_year}...")
    tuning, tuning_meta = _score_year(frame, args.tune_year)
    print(f"Tuning year {args.tune_year}: {len(tuning):,} predictions")

    print(f"Searching Prime ranking weights for top {args.top_n} picks/day...")
    selected_weights, leaderboard = _tune_weights(tuning, args.top_n)
    tuning_scored = _apply_weights(tuning, selected_weights)

    print(f"Selected weights: {selected_weights}")
    print(f"Building untouched validation predictions for {args.validation_year}...")
    validation, validation_meta = _score_year(frame, args.validation_year)
    validation_scored = _apply_weights(validation, selected_weights)

    # Probability-only baseline: if composite Prime ranking does not improve this
    # on untouched validation, we should not pretend the extra score adds value.
    tuning_prime_top = _top_n_report(tuning_scored, "prime_score")
    validation_prime_top = _top_n_report(validation_scored, "prime_score")
    tuning_probability_top = _top_n_report(tuning_scored, "winner_probability")
    validation_probability_top = _top_n_report(validation_scored, "winner_probability")

    selected_n = str(args.top_n)
    prime_validation_acc = validation_prime_top[selected_n]["accuracy"]
    baseline_validation_acc = validation_probability_top[selected_n]["accuracy"]
    delta = None
    if prime_validation_acc is not None and baseline_validation_acc is not None:
        delta = float(prime_validation_acc - baseline_validation_acc)

    report = {
        "status": "READ_ONLY_EVALUATION",
        "data": {
            "canonical_completed_matches": int(len(matches)),
            "feature_rows": int(len(frame)),
            "available_years": years,
            "tune_year": args.tune_year,
            "validation_year": args.validation_year,
            "prime_shelf_size": args.top_n,
        },
        "method": {
            "base_model": (
                "For each evaluated year, train/calibration contain only earlier matches. "
                "Probabilities use the same forward/reverse symmetry principle as production inference."
            ),
            "prime_tuning": (
                "Prime weights are searched only on the tuning year's out-of-time predictions. "
                "The selected weights are then frozen and evaluated on the later validation year."
            ),
            "components": {
                "model_probability": "calibrated winner probability strength, normalized so 50%=0 and 100%=1",
                "data_depth": "point-in-time FeatureBuilder data_depth",
                "factor_agreement": "directional agreement of Elo/surface/ranking/form/H2H/workload signals",
            },
        },
        "selected_weights": selected_weights,
        "weight_search_top20": leaderboard,
        "tuning": {
            **tuning_meta,
            "prime_top_n_per_day": tuning_prime_top,
            "probability_only_top_n_per_day": tuning_probability_top,
            "prime_thresholds": _threshold_report(tuning_scored),
        },
        "validation": {
            **validation_meta,
            "prime_top_n_per_day": validation_prime_top,
            "probability_only_top_n_per_day": validation_probability_top,
            "prime_thresholds": _threshold_report(validation_scored),
        },
        "decision": {
            "selected_top_n": args.top_n,
            "validation_prime_accuracy": prime_validation_acc,
            "validation_probability_only_accuracy": baseline_validation_acc,
            "validation_accuracy_delta": delta,
            "prime_ranking_beats_probability_only": bool(delta is not None and delta > 0),
            "note": (
                "Do not promote the composite Prime ranking merely because it wins on the tuning year. "
                "The untouched validation result is the decision signal."
            ),
        },
    }

    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print("\n=== PRIME VALIDATION SUMMARY ===")
    print(json.dumps({"selected_weights": selected_weights, "decision": report["decision"]}, indent=2))
    print(f"Report written to: {path}")
    print("READ ONLY: no Supabase rows were modified and no Tennis API calls were made.")


if __name__ == "__main__":
    main()
