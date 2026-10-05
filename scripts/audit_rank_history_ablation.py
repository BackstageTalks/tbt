"""Matched ATP/WTA ranking-history ablation on current canonical history.

Both arms are freshly fitted on identical chronological partitions. The only
difference is the leakage-safe weekly ATP/WTA rank-history feature groups.
Read-only research: no provider API, no selector changes, no model export.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import json
from pathlib import Path

import numpy as np
import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from audit_high_impact import fitted_model_boundary, metrics
from audit_quality_group_ablation import paired_delta
from release_store import ReleaseStore
from tbt.data.atp_rank_history import ATP_RANK_HISTORY_FEATURE_NAMES
from tbt.data.wta_rank_history import WTA_RANK_HISTORY_FEATURE_NAMES

RANK_FEATURES = list(ATP_RANK_HISTORY_FEATURE_NAMES) + list(WTA_RANK_HISTORY_FEATURE_NAMES)


def chronological_partitions(frame: pd.DataFrame, boundary: pd.Timestamp):
    dates = pd.to_datetime(frame["scheduled_at"], utc=True, errors="coerce")
    if dates.isna().any() or frame["match_id"].duplicated().any():
        raise ValueError("Invalid dates or duplicate event identities")
    if not frame["target"].isin([0, 1]).all():
        raise ValueError("Invalid binary target")
    day = dates.dt.normalize()
    train = (day >= pd.Timestamp("2021-01-01", tz="UTC")) & (day < pd.Timestamp("2026-07-01", tz="UTC"))
    calibration = (day >= pd.Timestamp("2026-07-01", tz="UTC")) & (day < pd.Timestamp("2026-09-01", tz="UTC"))
    test = day > max(pd.Timestamp("2026-09-25", tz="UTC"), boundary.normalize())
    parts = [frame.loc[mask].copy() for mask in (train, calibration, test)]
    if min(map(len, parts)) == 0:
        raise ValueError("Empty chronological rank-history partition")
    ids = [set(part["match_id"]) for part in parts]
    if any(ids[i] & ids[j] for i in range(3) for j in range(i)):
        raise ValueError("Rank-history partitions overlap")
    return parts


def arm_metrics(probabilities, test: pd.DataFrame):
    out = {"all_events": metrics(probabilities, test["target"])}
    out["by_tour"] = {}
    tours = test["tour"].astype(str).to_numpy()
    for tour, group in test.groupby("tour"):
        mask = tours == str(tour)
        out["by_tour"][str(tour)] = metrics(probabilities[mask], group["target"])
    return out


def main():
    from sklearn.base import clone
    from tbt.models.artifact import load_model
    from tbt.models.ensemble import TennisEnsemble

    ap = argparse.ArgumentParser()
    ap.add_argument("--training-table", required=True)
    ap.add_argument("--training-report", required=True)
    ap.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    ap.add_argument("--out", default=".cache/tbt/rank-history-ablation/report.json")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.read_parquet(args.training_table)
    table_report = json.loads(Path(args.training_report).read_text(encoding="utf-8"))
    if len(frame) != int(table_report.get("rows") or -1):
        raise ValueError("Training table row count mismatch")

    required = set(RANK_FEATURES)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("Rank-history columns missing: " + ", ".join(missing))

    model_dir = out.parent / "champion"
    ReleaseStore(args.data_repository, "tbt-model-production-v1", model_dir).download(
        extra_names=("model.joblib", "training_report.json"),
        required_names=("model.joblib", "training_report.json"),
    )
    champion = load_model(str(model_dir / "model.joblib"))
    boundary = fitted_model_boundary(champion.metadata)
    train, calibration, test = chronological_partitions(frame, boundary)

    rank_coverage = {
        "atp_known_both": float(pd.to_numeric(frame.get("atp_hist_known_both", 0), errors="coerce").fillna(0).mean()),
        "wta_known_both": float(pd.to_numeric(frame.get("wta_hist_known_both", 0), errors="coerce").fillna(0).mean()),
    }

    report = {
        "schema": 1,
        "purpose": "matched_rank_history_research_not_promotion",
        "phase": "inputs_verified",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider_requests": 0,
        "production_mutated": False,
        "champion_version": champion.version,
        "test_after_fitting_boundary": str(boundary),
        "source_training_table": table_report,
        "rank_features": RANK_FEATURES,
        "rank_coverage": rank_coverage,
        "partitions": {
            name: {
                "n": len(part),
                "first": str(pd.to_datetime(part["scheduled_at"], utc=True).min()),
                "last": str(pd.to_datetime(part["scheduled_at"], utc=True).max()),
            }
            for name, part in (("train", train), ("calibration", calibration), ("test", test))
        },
        "fixed_choices": {
            "blend_weight_boost": champion.blend_weight,
            "elo_weight": champion.elo_weight,
            "calibrator_kind": champion.calibrator.kind,
            "estimator_family": champion.__class__.__name__,
        },
        "limitations": [
            "Retrospective reconstructed history; not an untouched promotion gate.",
            "Source dates are point-in-time safe, but identity coverage differs by tour.",
            "Probability metrics only; this table does not establish yield or CLV.",
            "Promotion remains blocked until a fresh untouched holdout passes tour-specific gates.",
        ],
        "arms": {},
    }
    write = lambda: out.write_text(json.dumps(report, indent=2, allow_nan=False, default=str), encoding="utf-8")
    write()

    probabilities = {}
    arms = [
        ("fresh_without_rank_history", list(champion.feature_names)),
        ("fresh_with_rank_history", list(champion.feature_names) + RANK_FEATURES),
    ]
    for name, feature_names in arms:
        model = TennisEnsemble(feature_names=feature_names)
        model.linear = clone(champion.linear)
        model.boost = clone(champion.boost)
        model.excluded_features = set(champion.excluded_features)
        model.fit_frozen(
            train,
            calibration,
            blend_weight=champion.blend_weight,
            elo_weight=champion.elo_weight,
            calibrator_kind=champion.calibrator.kind,
        )
        p = model.predict_proba(test)
        probabilities[name] = p
        variance = model.linear.named_steps["scale"].var_
        rank_variance = {
            feature: float(variance[model.feature_names.index(feature)])
            for feature in RANK_FEATURES
            if feature in model.feature_names
        }
        report["arms"][name] = {
            **arm_metrics(p, test),
            "rank_training_variance": rank_variance,
            "feature_count": len(model.feature_names),
        }
        report["phase"] = name
        write()
        del model
        gc.collect()

    a = probabilities["fresh_without_rank_history"]
    b = probabilities["fresh_with_rank_history"]
    report["rank_history_minus_baseline"] = paired_delta(a, b, test["target"])
    report["by_tour_delta"] = {}
    tours = test["tour"].astype(str).to_numpy()
    y = test["target"].to_numpy()
    for tour in sorted(set(tours)):
        mask = tours == tour
        if int(mask.sum()) >= 50:
            report["by_tour_delta"][tour] = paired_delta(a[mask], b[mask], y[mask])

    report["phase"] = "complete"
    write()
    print(json.dumps({
        "phase": "complete",
        "test_n": len(test),
        "delta": report["rank_history_minus_baseline"],
        "by_tour": report["by_tour_delta"],
    }), flush=True)


if __name__ == "__main__":
    main()
