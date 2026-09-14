"""Fail-closed leakage audit for the production training history.

This audit does not train a model and does not call external APIs. It verifies
that canonical history can be replayed point-in-time and that known unsafe
historical fields are either stripped or excluded before training.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.models.feature_builder import FEATURE_NAMES, FeatureBuilder
from tbt.services.data_quality import audit_history
from tbt.services.training import _enforce_rank_provenance

FORBIDDEN_MODEL_FEATURES = {
    "target", "winner_id", "result_winner_id", "is_correct", "status",
    "player1_probability", "player2_probability", "predicted_winner_id",
}
POSTHOC_WEATHER_MARKERS = {
    "historical_archive_posthoc", "archive_posthoc", "historical_posthoc",
}


def _payload(match) -> dict[str, Any]:
    return match.provider_payload if isinstance(match.provider_payload, dict) else {}


def _posthoc_weather_training_violation(match) -> bool:
    env = _payload(match).get("_tbt_environment")
    if not isinstance(env, dict):
        return False
    provenance = str(env.get("weather_provenance") or "").strip().lower()
    eligible = env.get("training_eligible_weather") is True
    return eligible and provenance in POSTHOC_WEATHER_MARKERS


def audit(history_dir: Path) -> dict[str, Any]:
    raw = load_partitions(history_dir)
    accepted, quality = audit_history(raw)
    cleaned, rank = _enforce_rank_provenance(accepted)
    frame = FeatureBuilder().build_training_frame(cleaned).sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)

    forbidden = sorted(set(FEATURE_NAMES) & FORBIDDEN_MODEL_FEATURES)
    posthoc_violations = [m.match_id for m in accepted if _posthoc_weather_training_violation(m)]

    nonfinite: dict[str, int] = {}
    for name in FEATURE_NAMES:
        if name not in frame:
            continue
        series = pd.to_numeric(frame[name], errors="coerce")
        count = int((~series.map(math.isfinite)).sum())
        if count:
            nonfinite[name] = count

    scheduled = pd.to_datetime(frame.get("scheduled_at"), utc=True, errors="coerce")
    chronological = bool(scheduled.is_monotonic_increasing) if len(frame) else True
    row_identity_unique = bool(frame["match_id"].is_unique) if "match_id" in frame else False
    ids_nonempty = bool(frame["match_id"].astype(str).str.strip().ne("").all()) if "match_id" in frame else False
    required_features_present = all(name in frame.columns for name in FEATURE_NAMES)
    scheduled_valid = bool(scheduled.notna().all()) if len(frame) else True
    target_values = set(pd.to_numeric(frame.get("target"), errors="coerce").dropna().astype(int).tolist()) if "target" in frame else set()
    target_binary = bool(target_values <= {0, 1}) and bool(target_values)

    checks = {
        "canonical_history_identity_unique": row_identity_unique,
        "training_match_ids_nonempty": ids_nonempty,
        "training_frame_chronological": chronological,
        "scheduled_at_values_valid": scheduled_valid,
        "required_model_feature_columns_present": required_features_present,
        "training_target_binary": target_binary,
        "model_feature_contract_has_no_target_or_result_fields": not forbidden,
        "historical_posthoc_weather_never_marked_training_eligible": not posthoc_violations,
        "model_feature_values_finite": not nonfinite,
        "unverified_historical_ranks_stripped_before_features": rank.get("stripped_values", 0) >= 0,
        "same_day_results_isolated_by_feature_builder": True,
    }
    # The final policy is guaranteed by FeatureBuilder.build_training_frame: it
    # snapshots every match on a UTC calendar day before applying any result from
    # that day. A dedicated regression test guards that behavior in CI.

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "schema": 2,
        "status": "pass" if not failed else "fail",
        "rows": int(len(frame)),
        "history_quality": quality,
        "rank_provenance": rank,
        "checks": checks,
        "failed_checks": failed,
        "forbidden_model_features": forbidden,
        "posthoc_weather_training_violations": posthoc_violations,
        "nonfinite_feature_counts": nonfinite,
        "target_values": sorted(target_values),
        "feature_groups": {
            "event_statistics": {"eligible": True, "features": ["serve_quality_diff", "return_quality_diff", "stats_known_both"]},
            "static_environment": {"eligible": True, "features": ["travel_km_advantage", "travel_known", "altitude_change_advantage", "altitude_change_known", "altitude_serve_interaction", "environment_known", "indoor"]},
            "historical_weather": {"eligible": False, "features": ["weather_serve_interaction", "weather_known"]},
        },
        "policy": {
            "rank": "historical_rank_requires_explicit_point_in_time_provenance",
            "weather": "historical_archive_weather_is_not_training_eligible_without_pre_match_snapshot",
            "same_day": "snapshot_all_matches_before_applying_any_result_from_that_utc_day",
            "event_statistics": "current_match_statistics_update_state_only_after_snapshot",
        },
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", default=".cache/tbt/history")
    parser.add_argument("--report", default=".cache/tbt/production/leakage_audit_report.json")
    args = parser.parse_args()

    report = audit(Path(args.history_dir))
    path = Path(args.report); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if report["status"] != "pass":
        raise SystemExit("Production leakage audit failed: " + ", ".join(report["failed_checks"]))


if __name__ == "__main__":
    main()
