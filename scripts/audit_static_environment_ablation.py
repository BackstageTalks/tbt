"""Read-only matched chronological static-Environment ablation.

This is a diagnostic linear-model ablation, NOT production-model evidence or
an automated promotion decision. Both arms train on the identical date split
and rows. ES features and post-hoc archive weather are excluded in both arms.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from _bootstrap import ROOT
from tbt.models.feature_builder import FEATURE_NAMES
from build_production_training_table import (
    STATIC_ENV_FEATURES, WEATHER_RESEARCH_FEATURES, ES_FEATURES,
)

# Include other event-statistics features in the shared exclusion, so that
# sparse post-hoc enrichment cannot masquerade as an Environment gain.
OTHER_ES_FEATURES = (
    "surface_serve_quality_diff", "surface_return_quality_diff",
    "surface_stats_known_both",
)
EXCLUDED = set(WEATHER_RESEARCH_FEATURES + ES_FEATURES) | set(OTHER_ES_FEATURES)
STATIC = set(STATIC_ENV_FEATURES)


def split_dates(frame: pd.DataFrame, fraction: float = 0.8):
    if not 0 < fraction < 1:
        raise ValueError("Invalid chronological split fraction")
    dates = pd.to_datetime(frame["scheduled_at"], utc=True).dt.floor("D")
    days = sorted(dates.dropna().unique())
    if len(days) < 30:
        raise ValueError("At least 30 distinct UTC match days required")
    boundary = days[max(1, int(len(days) * fraction)) - 1]
    train = dates <= boundary
    test = dates > boundary
    if not train.any() or not test.any() or dates.isna().any():
        raise ValueError("Empty split or invalid timestamps")
    return train, test, str(boundary)


def _metrics(truth: np.ndarray, probabilities: np.ndarray) -> dict:
    if len(truth) == 0:
        return {"rows": 0}
    clipped = np.clip(probabilities, 1e-6, 1 - 1e-6)
    result = {
        "rows": len(truth),
        "accuracy": float(accuracy_score(truth, clipped >= 0.5)),
        "brier": float(brier_score_loss(truth, clipped)),
        "log_loss": float(log_loss(truth, clipped, labels=[0, 1])),
    }
    if len(np.unique(truth)) == 2:
        result["roc_auc"] = float(roc_auc_score(truth, clipped))
    return result


def compare(frame: pd.DataFrame) -> dict:
    required = {"target", "scheduled_at", "match_id"}
    if not required.issubset(frame):
        raise ValueError("Training table lacks mandatory columns")
    train, test, cutoff = split_dates(frame)
    y_train = pd.to_numeric(frame.loc[train, "target"], errors="raise").astype(int)
    y_test = pd.to_numeric(frame.loc[test, "target"], errors="raise").astype(int)
    if not set(y_train.unique()).issubset({0, 1}) or len(y_train.unique()) < 2:
        raise ValueError("Binary training target is invalid")
    if not set(y_test.unique()).issubset({0, 1}):
        raise ValueError("Invalid holdout target")
    base = [f for f in FEATURE_NAMES if f not in EXCLUDED and f not in STATIC]
    extra = [f for f in STATIC_ENV_FEATURES if f in FEATURE_NAMES]
    missing = [f for f in base + extra if f not in frame]
    if missing:
        raise ValueError(f"Training table missing feature columns: {missing}")

    report = {
        "schema": 1,
        "purpose": "read_only_research_ablation_not_production_gate",
        "data_split": "chronological_whole_UTC_days_80_20",
        "train_rows": int(train.sum()),
        "holdout_rows": int(test.sum()),
        "train_last_day": cutoff,
        "holdout_first_day": str(pd.to_datetime(
            frame.loc[test, "scheduled_at"], utc=True
        ).min().date()),
        "base_features": base,
        "added_static_environment_features": extra,
        "excluded_posthoc_weather_features": WEATHER_RESEARCH_FEATURES,
        "excluded_event_statistics_features": sorted(EXCLUDED - set(WEATHER_RESEARCH_FEATURES)),
        "models": {},
        "limitations": [
            "Diagnostic logistic linear SGD, not the deployed ensemble",
            "Retrospectively reconstructed static venues may differ from information available before a historical match",
            "No automatic promotion; confirm with production chronological holdout/backtest",
        ],
    }
    known = pd.to_numeric(
        frame.loc[test, "environment_known"], errors="coerce"
    ).fillna(0).to_numpy() > 0

    for name, features in (("baseline", base), ("plus_static_environment", base + extra)):
        # Both arms use exactly the same training rows, holdout rows, model
        # family and hyperparameters. Only the static input group differs.
        xtrain = frame.loc[train, features].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
        xtest = frame.loc[test, features].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
        model = make_pipeline(
            SimpleImputer(strategy="constant", fill_value=0),
            StandardScaler(),
            SGDClassifier(
                loss="log_loss", alpha=0.0001,
                max_iter=35, tol=0.0001, random_state=42,
            ),
        )
        model.fit(xtrain, y_train)
        probabilities = model.predict_proba(xtest)[:, 1]
        report["models"][name] = {
            "all_holdout": _metrics(y_test.to_numpy(), probabilities),
            "environment_known_holdout": _metrics(
                y_test.to_numpy()[known], probabilities[known]
            ),
            "environment_unknown_holdout": _metrics(
                y_test.to_numpy()[~known], probabilities[~known]
            ),
        }

    for segment in ("all_holdout", "environment_known_holdout", "environment_unknown_holdout"):
        base_metrics = report["models"]["baseline"][segment]
        env_metrics = report["models"]["plus_static_environment"][segment]
        if base_metrics["rows"]:
            report.setdefault("environment_minus_baseline", {})[segment] = {
                metric: round(env_metrics[metric] - base_metrics[metric], 6)
                for metric in ("accuracy", "brier", "log_loss")
            }
    report["holdout_environment_known_rate"] = float(known.mean())
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", default=".cache/tbt/production/training_table.parquet")
    parser.add_argument("--out", default=".cache/tbt/environment-joint/ablation.json")
    args = parser.parse_args()
    frame = pd.read_parquet(args.table)
    report = compare(frame)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "train_rows": report["train_rows"],
        "holdout_rows": report["holdout_rows"],
        "environment_known_rate": report["holdout_environment_known_rate"],
        "baseline": report["models"]["baseline"]["all_holdout"],
        "with_environment": report["models"]["plus_static_environment"]["all_holdout"],
        "delta": report["environment_minus_baseline"]["all_holdout"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
