"""Matched chronological ablation for leakage-safe BlinQ court-speed candidates.

Read-only research. Uses the persisted verified production training table for the
base features and reconstructs court-speed candidates from the latest committed
canonical history. No Tennis RapidAPI calls, no production writes, no promotion.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import json
from pathlib import Path

import numpy as np
import pandas as pd

from _bootstrap import ROOT
from audit_high_impact import fitted_model_boundary, metrics
from audit_quality_group_ablation import partitions, paired_delta
from release_store import ReleaseStore
from tbt.data.court_speed import (
    COURT_SPEED_FEATURE_NAMES,
    CourtSpeedHistory,
    coverage_summary as court_speed_coverage_summary,
)
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.models.artifact import load_model
from tbt.models.feature_builder import FeatureBuilder
from tbt.models.ensemble import TennisEnsemble


def _download_verified_table(repo: str, directory: Path) -> tuple[pd.DataFrame, dict]:
    required = (
        "training_table.parquet",
        "training_table_report.json",
        "leakage_audit_report.json",
        "enrichment_summary.json",
    )
    store = ReleaseStore(repo, "tbt-training-table-v1", directory)
    store.download(
        extra_names=required,
        required_names=required,
        require_bundle_manifest=True,
    )
    table_report = json.loads((directory / "training_table_report.json").read_text())
    leakage = json.loads((directory / "leakage_audit_report.json").read_text())
    enrichment = json.loads((directory / "enrichment_summary.json").read_text())
    if leakage.get("status") != "pass":
        raise ValueError("Persisted training table leakage audit did not pass")
    if enrichment.get("status") != "validated":
        raise ValueError("Persisted training table enrichment is not validated")
    frame = pd.read_parquet(directory / "training_table.parquet")
    if len(frame) != table_report.get("rows"):
        raise ValueError("Persisted row count disagrees with training table report")
    if frame.match_id.duplicated().any():
        raise ValueError("Persisted training table contains duplicate match_id")
    return frame, table_report


def _court_speed_frame(repo: str, directory: Path, table_ids: set[str]) -> tuple[pd.DataFrame, dict]:
    store = ReleaseStore(repo, "tbt-data-v1", directory)
    store.download()
    matches, safety = sanitize_history_identities(load_partitions(directory))
    if safety.get("quarantined_rows"):
        raise ValueError("Canonical history identity quarantine is non-empty")
    source = {str(m.match_id): m for m in matches}
    missing = sorted(table_ids - set(source))
    if missing:
        raise ValueError(f"Canonical history missing {len(missing)} persisted training ids")

    history = CourtSpeedHistory(matches)
    rows = []
    for mid in sorted(table_ids):
        original = source[mid]
        oriented, _ = FeatureBuilder.orient_for_training(original)
        values = history.features_for_match(oriented)
        rows.append({"match_id": mid, **values})
    result = pd.DataFrame(rows)
    return result, court_speed_coverage_summary(rows)


def _fit_arm(champion, train, calibration, test, feature_names):
    from sklearn.base import clone

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
    return model, model.predict_proba(test)


def decision(delta: dict) -> dict:
    mean = float(delta["second_minus_first_log_loss"])
    interval = delta.get("approximate_paired_95pct_interval")
    if interval and interval[1] < 0 and mean < 0:
        verdict = "KEEP_CANDIDATE"
        reason = "court-speed improves paired log loss and the approximate 95% interval stays below zero"
    elif interval and interval[0] > 0 and mean > 0:
        verdict = "DROP"
        reason = "court-speed worsens paired log loss and the approximate 95% interval stays above zero"
    elif mean < 0:
        verdict = "HOLD_RESEARCH"
        reason = "direction is favorable but uncertainty overlaps zero"
    else:
        verdict = "DROP"
        reason = "no paired log-loss improvement on the fixed chronological holdout"
    return {"verdict": verdict, "reason": reason}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    ap.add_argument("--out", default=".cache/tbt/court-speed-ablation/report.json")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    table_dir = out.parent / "table"
    history_dir = out.parent / "history"
    champion_dir = out.parent / "champion"

    frame, table_report = _download_verified_table(args.data_repository, table_dir)
    table_ids = set(frame.match_id.astype(str))
    court, coverage = _court_speed_frame(args.data_repository, history_dir, table_ids)
    frame["match_id"] = frame.match_id.astype(str)
    frame = frame.merge(court, on="match_id", how="left", validate="one_to_one")
    if frame[COURT_SPEED_FEATURE_NAMES].isna().any().any():
        raise ValueError("Court-speed merge produced missing feature rows")

    ReleaseStore(args.data_repository, "tbt-model-production-v1", champion_dir).download(
        extra_names=("model.joblib", "training_report.json"),
        required_names=("model.joblib", "training_report.json"),
    )
    champion = load_model(str(champion_dir / "model.joblib"))
    boundary = fitted_model_boundary(champion.metadata)
    train, calibration, test = partitions(frame, boundary)
    del frame
    gc.collect()

    base_features = list(champion.feature_names)
    duplicate = sorted(set(base_features) & set(COURT_SPEED_FEATURE_NAMES))
    if duplicate:
        raise ValueError(f"Court-speed already exists in champion feature contract: {duplicate}")
    candidate_features = base_features + list(COURT_SPEED_FEATURE_NAMES)

    report = {
        "schema": 1,
        "purpose": "matched_court_speed_research_not_promotion",
        "phase": "inputs_verified",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider_requests": 0,
        "rapidapi_requests": 0,
        "production_mutated": False,
        "champion_version": champion.version,
        "test_after_fitting_boundary": str(boundary),
        "source_training_table": table_report,
        "court_speed_coverage": coverage,
        "court_speed_features": list(COURT_SPEED_FEATURE_NAMES),
        "historical_policy": (
            "court-speed snapshot for each match uses only completed earlier matches; "
            "current-event estimate requires prior completed event matches"
        ),
        "partitions": {
            name: {
                "n": len(part),
                "first": str(pd.to_datetime(part.scheduled_at, utc=True).min()),
                "last": str(pd.to_datetime(part.scheduled_at, utc=True).max()),
            }
            for name, part in (
                ("train", train),
                ("calibration", calibration),
                ("test", test),
            )
        },
        "arms": {},
        "limitations": [
            "Retrospective research, not an automatic production promotion gate.",
            "No odds in this table: probability quality is measured, not yield or CLV.",
            "Approximate paired interval does not fully model dependence across repeated players/days.",
        ],
    }

    def write():
        out.write_text(
            json.dumps(report, indent=2, allow_nan=False, default=str),
            encoding="utf-8",
        )

    model0, p0 = _fit_arm(champion, train, calibration, test, base_features)
    report["arms"]["without_court_speed"] = {
        "all_events": metrics(p0, test.target),
        "by_tour": {
            str(tour): metrics(p0[test.tour.to_numpy() == tour], group.target)
            for tour, group in test.groupby("tour")
        },
    }
    report["phase"] = "without_court_speed"
    write()
    del model0
    gc.collect()

    model1, p1 = _fit_arm(champion, train, calibration, test, candidate_features)
    variance = model1.linear.named_steps["scale"].var_
    report["arms"]["with_court_speed"] = {
        "all_events": metrics(p1, test.target),
        "court_speed_training_variance": {
            name: float(variance[model1.feature_names.index(name)])
            for name in COURT_SPEED_FEATURE_NAMES
        },
        "by_tour": {
            str(tour): metrics(p1[test.tour.to_numpy() == tour], group.target)
            for tour, group in test.groupby("tour")
        },
    }
    report["phase"] = "with_court_speed"
    write()
    del model1
    gc.collect()

    known = test.court_speed_known.to_numpy() > 0
    report["court_speed_minus_baseline"] = {}
    for label, mask in (
        ("all_events", np.ones(len(test), dtype=bool)),
        ("court_speed_known", known),
        ("court_speed_unknown", ~known),
    ):
        if mask.any():
            report["court_speed_minus_baseline"][label] = paired_delta(
                p0[mask], p1[mask], test.target.to_numpy()[mask]
            )

    report["decision"] = decision(report["court_speed_minus_baseline"]["all_events"])
    report["phase"] = "complete"
    write()
    print(json.dumps({
        "phase": "complete",
        "coverage": coverage,
        "delta": report["court_speed_minus_baseline"]["all_events"],
        "decision": report["decision"],
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
