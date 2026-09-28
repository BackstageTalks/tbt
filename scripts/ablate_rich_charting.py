#!/usr/bin/env python3
"""Paired walk-forward ablation for BlinQ rich Match Charting v2 features."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.models.ensemble import TennisEnsemble
from tbt.models.feature_builder import FEATURE_NAMES, FeatureBuilder
from tbt.models.metrics import evaluate_probabilities
from tbt.services.backtest_service import _calendar_safe_split
from tbt.services.training import _enforce_rank_provenance

RICH_FEATURES = [
    "first_strike_serve_diff",
    "return_in_play_diff",
    "return_depth_diff",
    "break_point_serve_diff",
    "break_point_return_diff",
    "net_efficiency_diff",
    "aggression_balance_diff",
    "rich_charting_known_both",
]


def _delta(left: dict, right: dict, key: str) -> float | None:
    a, b = left.get(key), right.get(key)
    if a is None or b is None:
        return None
    return float(a) - float(b)


def _paired_accuracy(full_correct: np.ndarray, base_correct: np.ndarray) -> dict:
    full_only = int(np.sum(full_correct & ~base_correct))
    base_only = int(np.sum(base_correct & ~full_correct))
    discordant = full_only + base_only
    # Two-sided exact McNemar/binomial test without scipy dependency.
    if discordant:
        p_value = float(binomtest(full_only, discordant, p=0.5, alternative="two-sided").pvalue)
    else:
        p_value = 1.0
    return {
        "full_only_correct": full_only,
        "base_only_correct": base_only,
        "discordant": discordant,
        "mcnemar_exact_p_value": float(p_value),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", default=".cache/tbt/history")
    ap.add_argument("--out", default=".cache/tbt/rich-ablation.json")
    ap.add_argument("--first-test-year", type=int, default=2023)
    args = ap.parse_args()

    raw = load_partitions(Path(args.history_dir))
    matches, identity = sanitize_history_identities(raw)
    matches, rank_provenance = _enforce_rank_provenance(matches)
    frame = FeatureBuilder().build_training_frame(matches)
    frame = frame.sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)
    frame["scheduled_at"] = pd.to_datetime(frame["scheduled_at"], utc=True)
    frame["year"] = frame["scheduled_at"].dt.year

    full_features = list(FEATURE_NAMES)
    base_features = [name for name in FEATURE_NAMES if name not in RICH_FEATURES]
    missing = [name for name in RICH_FEATURES if name not in FEATURE_NAMES]
    if missing:
        raise SystemExit(f"Rich features missing from FEATURE_NAMES: {missing}")

    folds = []
    all_target = []
    all_full = []
    all_base = []

    years = sorted(int(y) for y in frame["year"].unique() if int(y) >= args.first_test_year)
    for year in years:
        historical = frame[frame["year"] < year].copy()
        test = frame[frame["year"] == year].copy()
        if len(historical) < 1200 or len(test) < 100:
            continue
        train, calibration = _calendar_safe_split(historical)

        full_model = TennisEnsemble(feature_names=full_features).fit(train, calibration)
        base_model = TennisEnsemble(feature_names=base_features).fit(train, calibration)

        full_p = full_model.predict_proba(test)
        base_p = base_model.predict_proba(test)
        target = test["target"].astype(int).to_numpy()

        full_metrics = evaluate_probabilities(target, full_p)
        base_metrics = evaluate_probabilities(target, base_p)
        full_correct = (full_p >= .5) == target
        base_correct = (base_p >= .5) == target
        paired = _paired_accuracy(full_correct, base_correct)

        rich_known = test["rich_charting_known_both"].astype(float).to_numpy() > 0.5
        rich_known_count = int(rich_known.sum())
        rich_subset = None
        if rich_known_count:
            rich_subset = {
                "n": rich_known_count,
                "full": evaluate_probabilities(target[rich_known], full_p[rich_known]),
                "base": evaluate_probabilities(target[rich_known], base_p[rich_known]),
                "paired_accuracy": _paired_accuracy(
                    full_correct[rich_known], base_correct[rich_known]
                ),
            }
            rich_subset["delta_full_minus_base"] = {
                key: _delta(rich_subset["full"], rich_subset["base"], key)
                for key in ("accuracy", "roc_auc", "log_loss", "brier_score", "ece_10")
            }

        folds.append({
            "year": year,
            "train_rows": int(len(train)),
            "calibration_rows": int(len(calibration)),
            "test_rows": int(len(test)),
            "rich_known_test_rows": rich_known_count,
            "full": full_metrics,
            "base_without_rich": base_metrics,
            "delta_full_minus_base": {
                key: _delta(full_metrics, base_metrics, key)
                for key in ("accuracy", "roc_auc", "log_loss", "brier_score", "ece_10")
            },
            "paired_accuracy": paired,
            "rich_known_subset": rich_subset,
            "full_model_metadata": full_model.metadata,
            "base_model_metadata": base_model.metadata,
        })
        all_target.append(target)
        all_full.append(full_p)
        all_base.append(base_p)

    target = np.concatenate(all_target)
    full_p = np.concatenate(all_full)
    base_p = np.concatenate(all_base)
    full_metrics = evaluate_probabilities(target, full_p)
    base_metrics = evaluate_probabilities(target, base_p)
    full_correct = (full_p >= .5) == target
    base_correct = (base_p >= .5) == target

    payload = {
        "schema": 1,
        "method": "paired calendar-year walk-forward ablation; identical folds/models; only rich Match Charting v2 features removed from base arm",
        "identity_safety": identity,
        "rank_provenance": rank_provenance,
        "rich_features": RICH_FEATURES,
        "full_feature_count": len(full_features),
        "base_feature_count": len(base_features),
        "tested_matches": int(len(target)),
        "overall": {
            "full": full_metrics,
            "base_without_rich": base_metrics,
            "delta_full_minus_base": {
                key: _delta(full_metrics, base_metrics, key)
                for key in ("accuracy", "roc_auc", "log_loss", "brier_score", "ece_10")
            },
            "paired_accuracy": _paired_accuracy(full_correct, base_correct),
        },
        "folds": folds,
    }
    target_path = ROOT / args.out
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "tested_matches": payload["tested_matches"],
        "delta": payload["overall"]["delta_full_minus_base"],
        "paired_accuracy": payload["overall"]["paired_accuracy"],
        "folds": [
            {
                "year": f["year"],
                "test_rows": f["test_rows"],
                "rich_known_test_rows": f["rich_known_test_rows"],
                "delta": f["delta_full_minus_base"],
            }
            for f in folds
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
