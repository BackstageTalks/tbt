"""Export the exact point-in-time training feature table plus coverage diagnostics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

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

    # Historical weather remains in the research columns for auditing only. The
    # production model masks these fields until genuine pre-match forecast
    # snapshots are stored. Static environment features remain training-eligible.
    source = {m.match_id: m for m in matches}
    frame["tour"] = frame.match_id.map(lambda key: source[key].tour)
    frame["tournament"] = frame.match_id.map(lambda key: source[key].tournament)
    frame["tournament_level_name"] = frame.match_id.map(lambda key: source[key].tournament_level)
    frame["indoor_known"] = frame.match_id.map(lambda key: source[key].indoor is not None).astype(float)

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False, engine="pyarrow")

    def mean(name):
        return float(pd.to_numeric(frame[name], errors="coerce").fillna(0).mean()) if name in frame else 0.0

    report = {
        "schema": 1,
        "rows": int(len(frame)),
        "history_quality": quality,
        "rank_provenance": rank_provenance,
        "model_features": list(FEATURE_NAMES),
        "static_environment": {
            "training_eligible": True,
            "features": STATIC_ENV_FEATURES,
            "travel_known_rate": mean("travel_known"),
            "altitude_change_known_rate": mean("altitude_change_known"),
            "indoor_known_rate": mean("indoor_known"),
            "venue_environment_known_rate": mean("environment_known"),
        },
        "event_statistics": {
            "training_eligible": True,
            "features": ES_FEATURES,
            "stats_known_both_rate": mean("stats_known_both"),
        },
        "historical_weather": {
            "training_eligible": False,
            "reason": "post_hoc_archive_weather_not_pre_match_forecast",
            "features_masked_by_model": WEATHER_RESEARCH_FEATURES,
            "weather_known_rate": mean("weather_known"),
        },
        "output": str(out),
    }
    report_path = Path(args.report); report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
