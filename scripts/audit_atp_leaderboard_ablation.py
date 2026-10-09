#!/usr/bin/env python3
"""Read-only, point-in-time ATP Serve/Return/Pressure leaderboard ablation.

Compare otherwise identical ATP models on the already published, leakage-audited
training table. Do not write canonical data, activate model weights, or select a
betting strategy using these retrospective results.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from release_store import ReleaseStore
from tbt.data.atp_leaderboards import ATP_LEADERBOARD_FEATURE_NAMES
from tbt.models.ensemble import TennisEnsemble
from tbt.models.metrics import evaluate_probabilities
from tbt.services.training import PRODUCTION_FEATURE_NAMES

# Fixed before looking at test outcomes. Whole UTC days prevent same-day mixing.
TRAIN_START = "2023-01-01"
TRAIN_END = "2026-07-01"
CAL_END = "2026-09-01"
FEATURES = list(PRODUCTION_FEATURE_NAMES) + list(ATP_LEADERBOARD_FEATURE_NAMES)
SCORING = ("accuracy", "log_loss", "brier_score", "ece_10", "roc_auc")


def split_atp(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    required = {"match_id", "tour", "scheduled_at", "target", *FEATURES}
    absent = sorted(required - set(frame.columns))
    if absent:
        raise ValueError(f"Missing causal training features: {absent}")
    if frame["match_id"].isna().any() or frame.match_id.duplicated().any():
        raise ValueError("Missing or duplicate match identities")
    if not frame.target.isin([0, 1]).all():
        raise ValueError("Invalid target")
    dates = pd.to_datetime(frame.scheduled_at, utc=True, errors="coerce")
    if dates.isna().any():
        raise ValueError("Invalid match date")

    atp = frame.loc[frame.tour.astype(str).str.lower() == "atp"].copy()
    days = dates.loc[atp.index].dt.normalize()
    beginning = pd.Timestamp(TRAIN_START, tz="UTC")
    train_end = pd.Timestamp(TRAIN_END, tz="UTC")
    cal_end = pd.Timestamp(CAL_END, tz="UTC")
    selections = (
        (days >= beginning) & (days < train_end),
        (days >= train_end) & (days < cal_end),
        days >= cal_end,
    )
    result = tuple(
        atp.loc[mask].sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)
        for mask in selections
    )
    ids = [set(part.match_id) for part in result]
    if (ids[0] & ids[1]) or (ids[0] & ids[2]) or (ids[1] & ids[2]):
        raise ValueError("Train, calibration and test identities overlap")
    return result


def make_arm(*, enabled: bool) -> TennisEnsemble:
    model = TennisEnsemble(feature_names=list(FEATURES))
    if not enabled:
        model.excluded_features.update(ATP_LEADERBOARD_FEATURE_NAMES)
    return model


def _metrics(target: np.ndarray, probabilities: np.ndarray) -> dict:
    if not len(target):
        return {}
    original = evaluate_probabilities(target, probabilities)
    return {
        key: (float(original[key]) if math.isfinite(float(original[key])) else None)
        for key in SCORING
    } | {"n": int(len(target))}


def paired_report(target: np.ndarray, baseline: np.ndarray, candidate: np.ndarray) -> dict:
    y = np.asarray(target, dtype=int)
    a = np.asarray(baseline, dtype=float)
    b = np.asarray(candidate, dtype=float)
    if not len(y) or y.shape != a.shape or a.shape != b.shape:
        raise ValueError("Paired test requires aligned nonempty targets and probabilities")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("Non-finite probabilities")
    base = _metrics(y, a)
    new = _metrics(y, b)
    deltas = {
        metric: None if base[metric] is None or new[metric] is None
        else new[metric] - base[metric]
        for metric in SCORING
    }
    # Per-event paired log-loss interval is descriptive; same-player/day effects
    # mean it is not a claim of independent observations or a promotion gate.
    a = np.clip(a, 1e-9, 1 - 1e-9)
    b = np.clip(b, 1e-9, 1 - 1e-9)
    loss_a = -(y * np.log(a) + (1 - y) * np.log(1 - a))
    loss_b = -(y * np.log(b) + (1 - y) * np.log(1 - b))
    diff = loss_b - loss_a
    se = float(diff.std(ddof=1) / math.sqrt(len(diff))) if len(diff) > 1 else None
    mean = float(diff.mean())
    return {
        "n": int(len(y)),
        "baseline": base,
        "candidate": new,
        "delta_candidate_minus_baseline": deltas,
        "paired_log_loss_delta": mean,
        "approximate_paired_95pct_interval": (
            [mean - 1.96 * se, mean + 1.96 * se] if se is not None else None
        ),
    }


def coverage(frame: pd.DataFrame) -> dict:
    n = len(frame)
    known = int((frame["atp_leaderboard_known_both"] > 0.5).sum()) if n else 0
    surface = int((frame["atp_surface_leaderboard_known_both"] > 0.5).sum()) if n else 0
    return {
        "atp_rows": n,
        "both_players_all_surface": known,
        "both_players_surface": surface,
        "both_players_rate": known / n if n else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    ap.add_argument("--out", default=".cache/tbt/atp-leaderboard-ablation/report.json")
    args = ap.parse_args()

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    cache = output.parent / "verified-table"
    asset_names = (
        "training_table.parquet", "training_table_report.json",
        "leakage_audit_report.json", "enrichment_summary.json",
    )
    store = ReleaseStore(args.data_repository, "tbt-training-table-v1", cache)
    store.download(extra_names=asset_names, required_names=asset_names, require_bundle_manifest=True)

    table_report = json.loads((cache / "training_table_report.json").read_text())
    leakage = json.loads((cache / "leakage_audit_report.json").read_text())
    enrichment = json.loads((cache / "enrichment_summary.json").read_text())
    source = table_report.get("atp_leaderboards") or {}
    if leakage.get("status") != "pass" or enrichment.get("status") != "validated":
        raise ValueError("Persisted training inputs failed leakage/enrichment verification")
    if source.get("historical_policy") != "previous_completed_season_only":
        raise ValueError("ATP leaderboard source lacks verified previous-season policy")
    if not source.get("source_csv") or source.get("production_enabled") is not False:
        raise ValueError("Unexpected ATP source or production activation")
    if not (float(source.get("known_both_rate") or 0) > 0):
        raise ValueError("No historical leaderboard observations available")

    required = sorted(set(FEATURES) | {"match_id", "tour", "target", "scheduled_at", "surface"})
    frame = pd.read_parquet(cache / "training_table.parquet", columns=required)
    if len(frame) != int(table_report.get("rows") or 0):
        raise ValueError("Persisted parquet row count mismatch")
    train, calibration, test = split_atp(frame)
    del frame
    gc.collect()
    sizes = (len(train), len(calibration), len(test))
    if sizes[0] < 1200 or sizes[1] < 120 or sizes[2] < 200:
        raise ValueError(f"Insufficient disjoint ATP research partitions: {sizes}")
    if not test.target.isin([0, 1]).all():
        raise ValueError("Invalid test outcomes")
    report = {
        "schema": 1,
        "phase": "inputs_verified",
        "purpose": "retrospective_research_not_model_promotion",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_mutated": False,
        "model_promoted": False,
        "provider_requests": 0,
        "source_release": "tbt-training-table-v1",
        "source_bundle_manifest": json.loads((cache / store.BUNDLE_MANIFEST).read_text()),
        "source_atp_leaderboards": source,
        "windows_utc": {
            "train": [TRAIN_START, TRAIN_END],
            "calibration": [TRAIN_END, CAL_END],
            "test_start": CAL_END,
            "upper_bounds_exclusive": True,
        },
        "partition_coverage": {
            name: coverage(part)
            for name, part in (
                ("train", train), ("calibration", calibration), ("test", test)
            )
        },
        "fixed_model_choices": {
            "feature_names": FEATURES,
            "blend_weight": 0.5,
            "elo_weight": 0.0,
            "calibrator_kind": "platt",
            "same_architecture_and_partitions": True,
            "difference": "ATP leaderboard columns masked to zero only in baseline",
        },
        "limitations": [
            "Retrospective single-period ATP-only ablation, not an untouched promotion gate.",
            "Seasonal features use previous completed year; current 52week/career excluded.",
            "No verified contemporaneous odds: ROI/yield/CLV cannot be established.",
            "Training release may lag the latest canonical snapshot.",
            "Per-event confidence intervals ignore player/day correlation.",
        ],
    }

    def save() -> None:
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False, default=str))

    save()
    probabilities = {}
    for name, enabled in (("baseline", False), ("candidate", True)):
        model = make_arm(enabled=enabled)
        model.fit_frozen(
            train, calibration,
            blend_weight=0.5, elo_weight=0.0, calibrator_kind="platt",
        )
        probabilities[name] = model.predict_proba(test)
        report["phase"] = f"fitted_{name}"
        save()
        print(json.dumps({"phase": report["phase"], "test_rows": len(test)}), flush=True)
        del model
        gc.collect()

    y = test.target.to_numpy(dtype=int)
    a, b = probabilities["baseline"], probabilities["candidate"]
    known = test.atp_leaderboard_known_both.to_numpy(dtype=float) > 0.5
    surface = test.atp_surface_leaderboard_known_both.to_numpy(dtype=float) > 0.5
    report["results"] = {}
    for key, mask in (
        ("all_atp", np.ones(len(test), dtype=bool)),
        ("both_player_stats_known", known),
        ("both_player_stats_missing", ~known),
        ("both_player_surface_known", surface),
    ):
        if mask.any():
            report["results"][key] = paired_report(y[mask], a[mask], b[mask])

    known_n = int(known.sum())
    # Diagnostic only, never automatically promote any model.
    report["research_signal"] = (
        "insufficient_paired_coverage" if known_n < 200
        else "measured_not_a_promotion_decision"
    )
    report["phase"] = "complete"
    save()
    print(json.dumps({
        "phase": "complete",
        "paired_known_test_rows": known_n,
        "all_atp_delta": report["results"]["all_atp"]["delta_candidate_minus_baseline"],
        "candidate_not_promoted": True,
    }), flush=True)


if __name__ == "__main__":
    main()
