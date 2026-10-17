"""7.2.1 read-only pre-match odds >1.50 specialist research.

Input must be a private point-in-time candidate replay CSV; do not commit rows.
Fits only a separate research calibrator, never changes CDB/champion or publishes picks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

VERSION = "7.2.1-market-specialist-research"
FEATURES = ["model_probability", "fair_market_probability", "data_depth", "odds"]
REQUIRED = set(FEATURES) | {
    "betting_day", "event_id", "selection_id", "quote_at",
    "snapshot_at", "scheduled_at", "outcome",
}


def _aware(series: pd.Series) -> pd.Series:
    if not series.astype(str).str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$").all():
        raise ValueError("Naive timestamp")
    dates = pd.to_datetime(series, errors="raise", format="ISO8601", utc=True)
    if dates.isna().any():
        raise ValueError("Missing timestamp")
    return dates


def validated_candidates(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required fields: {sorted(missing)}")
    data = frame.copy()
    for col in FEATURES:
        data[col] = pd.to_numeric(data[col], errors="raise")
    if not np.isfinite(data[FEATURES].to_numpy(dtype=float)).all():
        raise ValueError("Nonfinite input")
    if not (
        data.model_probability.between(0, 1, inclusive="neither")
        & data.fair_market_probability.between(0, 1, inclusive="neither")
        & data.data_depth.between(0, 1)
    ).all():
        raise ValueError("Invalid probability or data depth")
    for col in ("quote_at", "snapshot_at", "scheduled_at"):
        data[col] = _aware(data[col])
    if (data.quote_at > data.snapshot_at).any() or (
        data.snapshot_at >= data.scheduled_at
    ).any():
        raise ValueError("Look-ahead / timestamp mismatch")
    if not data.outcome.isin(("win", "loss", "pending", "void")).all():
        raise ValueError("Unknown outcome")
    if data[["betting_day", "event_id", "selection_id"]].duplicated().any():
        raise ValueError("Duplicate event/selection")
    priced = data.loc[data.odds > 1.50].copy()
    if priced.empty:
        raise ValueError("No strictly >1.50 priced pre-match candidates")
    return priced, {
        "source_rows": int(len(data)),
        "equal_150_excluded": int((data.odds == 1.50).sum()),
        "eligible_gt_150": int(len(priced)),
        "settled_gt_150": int(priced.outcome.isin(("win", "loss")).sum()),
    }


def _score(y, p):
    p = np.clip(np.asarray(p), 1e-6, 1 - 1e-6)
    return {
        "n": int(len(y)), "accuracy": float(accuracy_score(y, p >= 0.5)),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
    }


def _top_three(frame, column):
    # Select before looking at settlement; pending picks consume daily capacity.
    ranked = frame.sort_values(
        ["betting_day", column, "event_id"],
        ascending=[True, False, True], kind="stable",
    ).groupby("betting_day", sort=True, group_keys=False).head(3)
    settled = ranked.loc[ranked.outcome.isin(("win", "loss"))]
    n, wins = len(settled), int((settled.outcome == "win").sum())
    net = float(np.where(settled.outcome == "win", settled.odds - 1, -1).sum())
    return {
        "selected": int(len(ranked)), "settled": n, "wins": wins,
        "hit_rate": wins / n if n else None,
        "roi": net / n if n else None, "net_units": net,
        "days": int(frame.betting_day.nunique()),
    }


def train_and_compare(
    source: Path, output: Path, *,
    train_through: str | None = None,
    test_through: str | None = None,
    min_train: int = 50,
):
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    data, counts = validated_candidates(pd.read_csv(source))
    settled = data.loc[data.outcome.isin(("win", "loss"))].copy()
    days = sorted(settled.betting_day.unique())
    if len(days) < 5:
        raise ValueError("Need >=5 distinct settled betting days")
    cutoff, end = train_through or days[-4], test_through or days[-1]
    if cutoff >= end:
        raise ValueError("Nonchronological training/test split")
    training = settled.loc[settled.betting_day <= cutoff]
    test = settled.loc[
        (settled.betting_day > cutoff) & (settled.betting_day <= end)
    ].copy()
    offered = data.loc[
        (data.betting_day > cutoff) & (data.betting_day <= end)
    ].copy()
    if len(training) < min_train or len(test) < 20 or training.outcome.nunique() < 2:
        raise ValueError("Insufficient disjoint training/test outcomes")
    if set(training.event_id) & set(test.event_id):
        raise ValueError("Event leaks across train and test")
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=0.25, solver="lbfgs", max_iter=500),
    )
    model.fit(training[FEATURES], (training.outcome == "win").astype(int))
    test["specialist_probability"] = model.predict_proba(test[FEATURES])[:, 1]
    offered["specialist_probability"] = model.predict_proba(offered[FEATURES])[:, 1]
    y = (test.outcome == "win").astype(int)
    report = {
        "version": VERSION, "status": "RESEARCH_ONLY_NOT_PROMOTED",
        "input_sha256": sha256,
        "guardrails": {
            "odds": "strictly >1.50",
            "time": "quote_at <= snapshot_at < scheduled_at",
            "max_daily_picks": 3,
            "production_writes": 0,
            "original_champion_retrained": False,
        },
        "counts": counts,
        "train": {
            "last_day": str(cutoff), "settled": int(len(training)),
            "days": int(training.betting_day.nunique()),
        },
        "test": {
            "first_day": str(min(test.betting_day)), "last_day": str(end),
            "settled": int(len(test)), "days": int(test.betting_day.nunique()),
            "pool_including_pending": int(len(offered)),
        },
        "probability_metrics": {
            "blinq": _score(y, test.model_probability),
            "market": _score(y, test.fair_market_probability),
            "specialist": _score(y, test.specialist_probability),
        },
        "top_three_metrics": {
            "blinq": _top_three(offered, "model_probability"),
            "market": _top_three(offered, "fair_market_probability"),
            "specialist": _top_three(offered, "specialist_probability"),
        },
        "limitations": [
            "Small retrospective snapshot sample, previously explored",
            "Sample is conditioned on published model candidates, not full board",
            "No independently unseen forward holdout or fresh market coverage",
            "Only price-conditioned calibration of existing model, not a new tennis model",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False, ensure_ascii=False) + "\n"
    )
    joblib.dump(
        {"version": VERSION, "features": FEATURES, "model": model, "source_sha256": sha256},
        output / "research_model.joblib",
    )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--train-through")
    parser.add_argument("--test-through")
    args = parser.parse_args()
    report = train_and_compare(
        args.candidates, args.out,
        train_through=args.train_through, test_through=args.test_through,
    )
    print(json.dumps(report, allow_nan=False, ensure_ascii=False))


if __name__ == "__main__":
    main()
