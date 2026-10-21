"""7.2.1 read-only pre-match odds >=1.50 TOP specialist research.

Input must be a private point-in-time candidate replay CSV; do not commit rows.
Fits only a separate research calibrator, never changes CDB/champion or publishes picks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
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
    if not np.isfinite(data.odds.to_numpy(dtype=float)).all():
        raise ValueError("Nonfinite bookmaker odds")
    if not np.isfinite(data[[col for col in FEATURES if col != "odds"]].to_numpy(dtype=float)).all():
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
    # The published TOP selector does NOT rank on raw model probability.
    # It shrinks confidence towards 50/50 using observed data depth. An
    # experiment claiming superiority to TOP must compare against the
    # probability actually used by production (without treating the ad-hoc
    # shrinkage as empirically validated calibration).
    data["public_top_probability"] = (
        0.5 + (data.model_probability - 0.5) * data.data_depth
    )
    if "blinq_probability" in data:
        public = pd.to_numeric(data["blinq_probability"], errors="raise")
        if not np.isfinite(public.to_numpy(dtype=float)).all() or not np.allclose(
            public.to_numpy(dtype=float),
            data.public_top_probability.to_numpy(dtype=float),
            atol=1e-8, rtol=0,
        ):
            raise ValueError("Snapshot TOP probability disagrees with production rule")

    # Production TOP accepts exactly 1.50: excluding the boundary silently
    # removes genuine offers and biases the price-conditioned experiment.
    priced = data.loc[data.odds >= 1.50].copy()
    if priced.empty:
        raise ValueError("No >=1.50 priced pre-match candidates")
    settled = priced.outcome.isin(("win", "loss"))
    return priced, {
        "source_rows": int(len(data)),
        "equal_150_included": int((priced.odds == 1.50).sum()),
        "eligible_ge_150": int(len(priced)),
        "settled_ge_150": int(settled.sum()),
        "raw_model_ge_80_settled": int((settled & (priced.model_probability >= 0.80)).sum()),
        "public_top_ge_80_settled": int((settled & (priced.public_top_probability >= 0.80)).sum()),
    }


def _score(y, p):
    p = np.clip(np.asarray(p), 1e-6, 1 - 1e-6)
    return {
        "n": int(len(y)), "accuracy": float(accuracy_score(y, p >= 0.5)),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
    }


def _wilson_95(wins: int, n: int):
    """Binomial 95% interval; descriptive, not a post-selection guarantee."""
    if n < 1:
        return None
    z = 1.959963984540054
    p = wins / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    radius = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def _high_confidence_settled(frame, column):
    # Count reliability in the actual priced TOP universe. A tiny number of
    # apparent 80% bets is a research limitation, not an 80% product claim.
    priced = frame.loc[
        frame.outcome.isin(("win", "loss")) & (frame[column] >= 0.80)
    ]
    n = int(len(priced))
    wins = int((priced.outcome == "win").sum())
    interval = _wilson_95(wins, n)
    offered_n = int(len(frame))
    selected_n = int((frame[column] >= 0.80).sum())
    return {
        "settled": n,
        "wins": wins,
        "accuracy": wins / n if n else None,
        "mean_probability": float(priced[column].mean()) if n else None,
        "sample_sufficient_for_diagnostic": n >= 30,
        "selected_including_pending": selected_n,
        "offered": offered_n,
        "selection_coverage": selected_n / offered_n if offered_n else None,
        "accuracy_ci95_wilson": interval,
        "target_87_supported": n >= 100 and interval is not None and interval[0] >= 0.87,
    }


def _top_three(frame, column, *, minimum_probability=None):
    # Optional VIP research: a predeclared 80% gate, with no forced fill.
    # Select before settlement; pending picks consume daily capacity.
    eligible = frame if minimum_probability is None else frame.loc[
        frame[column] >= minimum_probability
    ]
    ranked = eligible.sort_values(
        ["betting_day", column, "event_id"],
        ascending=[True, False, True], kind="stable",
    ).groupby("betting_day", sort=True, group_keys=False).head(3)
    settled = ranked.loc[ranked.outcome.isin(("win", "loss"))]
    n, wins = len(settled), int((settled.outcome == "win").sum())
    net = float(np.where(settled.outcome == "win", settled.odds - 1, -1).sum())
    interval = _wilson_95(wins, n)
    return {
        "selected": int(len(ranked)), "settled": n, "wins": wins,
        "hit_rate": wins / n if n else None,
        "hit_rate_ci95_wilson": interval,
        "target_87_supported": n >= 100 and interval is not None and interval[0] >= 0.87,
        "unsettled_selected": int(len(ranked) - n),
        "offered": int(len(frame)),
        "selection_coverage": len(ranked) / len(frame) if len(frame) else None,
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
            "odds": ">=1.50 including the exact TOP boundary",
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
            "blinq": _score(y, test.public_top_probability),
            "raw_model": _score(y, test.model_probability),
            "market": _score(y, test.fair_market_probability),
            "specialist": _score(y, test.specialist_probability),
        },
        "top_three_metrics": {
            "blinq": _top_three(offered, "public_top_probability"),
            "raw_model": _top_three(offered, "model_probability"),
            "market": _top_three(offered, "fair_market_probability"),
            "specialist": _top_three(offered, "specialist_probability"),
        },
        "vip_selective_metrics": {
            "blinq": _top_three(offered, "public_top_probability", minimum_probability=.80),
            "raw_model": _top_three(offered, "model_probability", minimum_probability=.80),
            "market": _top_three(offered, "fair_market_probability", minimum_probability=.80),
            "specialist": _top_three(offered, "specialist_probability", minimum_probability=.80),
        },
        "top_80_reliability": {
            "blinq": _high_confidence_settled(test, "public_top_probability"),
            "raw_model": _high_confidence_settled(test, "model_probability"),
            "specialist": _high_confidence_settled(test, "specialist_probability"),
        },
        "vip_accuracy_goal": {
            "target": 0.87,
            "minimum_settled_for_claim": 100,
            "criterion": "95% Wilson lower bound >= 0.87 on disjoint settled priced picks",
            "status": "RESEARCH_ONLY_NOT_PROMOTED",
            "coverage_must_be_reported": True,
            "research_minimum_probability": 0.80,
            "daily_max": 3,
            "no_forced_picks": True,
        },
        "limitations": [
            "Small retrospective snapshot sample, previously explored",
            "Existing candidate data may be conditioned on the old selector; full-board coverage is not established",
            "The public TOP baseline uses data-depth-shrunk probability, not raw model probability",
            "80% reliability requires independently unseen, adequately sized priced holdout",
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
