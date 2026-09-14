"""Export the point-in-time production training table plus coverage diagnostics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.models.feature_builder import FEATURE_NAMES, FeatureBuilder
from tbt.services.data_quality import audit_history
from tbt.services.training import _enforce_rank_provenance

STATIC_ENV_FEATURES = [
    "travel_km_advantage", "travel_known",
    "altitude_change_advantage", "altitude_change_known",
    "altitude_serve_interaction", "environment_known", "indoor",
]
WEATHER_RESEARCH_FEATURES = ["weather_serve_interaction", "weather_known"]
ES_FEATURES = ["serve_quality_diff", "return_quality_diff", "stats_known_both"]


def _mean(frame: pd.DataFrame, name: str) -> float:
    if name not in frame or frame.empty:
        return 0.0
    return float(pd.to_numeric(frame[name], errors="coerce").fillna(0).mean())


def _missing_rates(frame: pd.DataFrame, names: list[str]) -> dict[str, float]:
    out = {}
    for name in names:
        if name not in frame:
            out[name] = 1.0
        else:
            out[name] = round(float(frame[name].isna().mean()), 6)
    return out


def _segment(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": int(len(frame)),
        "stats_known_both_rate": round(_mean(frame, "stats_known_both"), 6),
        "environment_known_rate": round(_mean(frame, "environment_known"), 6),
        "travel_known_rate": round(_mean(frame, "travel_known"), 6),
        "altitude_change_known_rate": round(_mean(frame, "altitude_change_known"), 6),
        "indoor_known_rate": round(_mean(frame, "indoor_known"), 6),
        "weather_known_research_only_rate": round(_mean(frame, "weather_known"), 6),
    }


def _group_coverage(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    if column not in frame:
        return {}
    result = {}
    for key, group in frame.groupby(column, dropna=False, sort=True):
        label = "unknown" if pd.isna(key) or str(key).strip() == "" else str(key)
        result[label] = _segment(group)
    return result


def build_report(frame: pd.DataFrame, quality: dict, rank_provenance: dict) -> dict[str, Any]:
    return {
        "schema": 2,
        "rows": int(len(frame)),
        "date_range": {
            "from": None if frame.empty else str(pd.to_datetime(frame["scheduled_at"], utc=True).min()),
            "to": None if frame.empty else str(pd.to_datetime(frame["scheduled_at"], utc=True).max()),
        },
        "history_quality": quality,
        "rank_provenance": rank_provenance,
        "model_features": list(FEATURE_NAMES),
        "feature_missing_rate": _missing_rates(frame, list(FEATURE_NAMES)),
        "static_environment": {
            "training_eligible": True,
            "features": STATIC_ENV_FEATURES,
            "travel_known_rate": _mean(frame, "travel_known"),
            "altitude_change_known_rate": _mean(frame, "altitude_change_known"),
            "indoor_known_rate": _mean(frame, "indoor_known"),
            "venue_environment_known_rate": _mean(frame, "environment_known"),
        },
        "event_statistics": {
            "training_eligible": True,
            "features": ES_FEATURES,
            "stats_known_both_rate": _mean(frame, "stats_known_both"),
        },
        "historical_weather": {
            "training_eligible": False,
            "reason": "post_hoc_archive_weather_not_pre_match_forecast",
            "features_masked_by_model": WEATHER_RESEARCH_FEATURES,
            "weather_known_rate": _mean(frame, "weather_known"),
        },
        "coverage": {
            "overall": _segment(frame),
            "by_tour": _group_coverage(frame, "tour"),
            "by_year": _group_coverage(frame, "year"),
            "by_surface": _group_coverage(frame, "surface"),
        },
        "candidate_feature_groups": {
            "event_statistics": {"eligible_for_candidate": True, "features": ES_FEATURES},
            "static_environment": {"eligible_for_candidate": True, "features": STATIC_ENV_FEATURES},
            "historical_weather": {"eligible_for_candidate": False, "features": WEATHER_RESEARCH_FEATURES},
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", default=".cache/tbt/history")
    parser.add_argument("--out", default=".cache/tbt/training_table.parquet")
    parser.add_argument("--report", default=".cache/tbt/training_table_report.json")
    args = parser.parse_args()

    matches = load_partitions(Path(args.history_dir))
    matches, quality = audit_history(matches)
    matches, rank_provenance = _enforce_rank_provenance(matches)
    frame = FeatureBuilder().build_training_frame(matches).sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)

    # Historical weather is retained only for audit/research and remains masked
    # by the production model. Static environment and ES are candidate-eligible.
    source = {m.match_id: m for m in matches}
    frame["tour"] = frame.match_id.map(lambda key: source[key].tour)
    frame["tournament"] = frame.match_id.map(lambda key: source[key].tournament)
    frame["tournament_level_name"] = frame.match_id.map(lambda key: source[key].tournament_level)
    frame["surface"] = frame.match_id.map(lambda key: source[key].surface or "unknown")
    frame["indoor_known"] = frame.match_id.map(lambda key: source[key].indoor is not None).astype(float)
    frame["year"] = pd.to_datetime(frame["scheduled_at"], utc=True).dt.year.astype(str)

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False, engine="pyarrow")

    report = build_report(frame, quality, rank_provenance)
    report["output"] = str(out)
    report_path = Path(args.report); report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
