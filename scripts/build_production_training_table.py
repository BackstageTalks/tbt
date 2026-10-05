"""Export the point-in-time production training table plus coverage diagnostics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.atp_leaderboards import (
    ATPLeaderboardPriors,
    ATP_LEADERBOARD_FEATURE_NAMES,
    coverage_summary as atp_coverage_summary,
)
from tbt.data.atp_rank_history import (
    ATPRankHistory,
    ATP_RANK_HISTORY_FEATURE_NAMES,
    coverage_summary as atp_rank_history_coverage_summary,
)
from tbt.data.wta_season_stats import (
    WTASeasonPriors,
    WTA_SEASON_FEATURE_NAMES,
    coverage_summary as wta_coverage_summary,
)
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

# Coverage gates are data-readiness gates, not model-quality/promotion gates.
# They prevent a handful of enriched rows from being mislabeled as enough to
# run a meaningful candidate ablation. Promotion still depends on the later
# chronological holdout/backtest governance.
ES_READY_MIN_COVERAGE = 0.70
STATIC_ENV_READY_MIN_COVERAGE = 0.80


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
    es_rate = _mean(frame, "stats_known_both")
    env_rate = _mean(frame, "environment_known")
    raw_stats_matches = int((quality or {}).get("with_statistics") or 0)
    raw_stats_rate = (raw_stats_matches / len(frame)) if len(frame) else 0.0
    # Schema eligibility means the feature group is safe by provenance. Data
    # readiness separately answers whether this concrete history has enough
    # coverage for a meaningful candidate evaluation. A few observed rows are
    # explicitly not enough to declare a group ready.
    es_observed = es_rate > 0.0
    env_observed = env_rate > 0.0
    es_ready = es_rate >= ES_READY_MIN_COVERAGE
    env_ready = env_rate >= STATIC_ENV_READY_MIN_COVERAGE
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
            "has_observations": env_observed,
            "ready_for_candidate_eval": env_ready,
            "readiness_min_coverage": STATIC_ENV_READY_MIN_COVERAGE,
            "features": STATIC_ENV_FEATURES,
            "travel_known_rate": _mean(frame, "travel_known"),
            "altitude_change_known_rate": _mean(frame, "altitude_change_known"),
            "indoor_known_rate": _mean(frame, "indoor_known"),
            "venue_environment_known_rate": env_rate,
        },
        "event_statistics": {
            "training_eligible": True,
            "has_observations": es_observed,
            "ready_for_candidate_eval": es_ready,
            "readiness_min_coverage": ES_READY_MIN_COVERAGE,
            "features": ES_FEATURES,
            "stats_known_both_rate": es_rate,
            "raw_statistics_matches": raw_stats_matches,
            "raw_statistics_match_rate": raw_stats_rate,
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
            "event_statistics": {
                "schema_eligible": True,
                "has_observations": es_observed,
                "eligible_for_candidate": es_ready,
                "ready_for_candidate_eval": es_ready,
                "coverage": es_rate,
                "min_coverage": ES_READY_MIN_COVERAGE,
                "features": ES_FEATURES,
            },
            "static_environment": {
                "schema_eligible": True,
                "has_observations": env_observed,
                "eligible_for_candidate": env_ready,
                "ready_for_candidate_eval": env_ready,
                "coverage": env_rate,
                "min_coverage": STATIC_ENV_READY_MIN_COVERAGE,
                "features": STATIC_ENV_FEATURES,
            },
            "historical_weather": {"eligible_for_candidate": False, "features": WEATHER_RESEARCH_FEATURES},
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", default=".cache/tbt/history")
    parser.add_argument("--out", default=".cache/tbt/training_table.parquet")
    parser.add_argument("--report", default=".cache/tbt/training_table_report.json")
    parser.add_argument(
        "--atp-leaderboards-csv",
        default="",
        help=(
            "Official ATP leaderboard master CSV. Historical rows use only the "
            "previous completed season; current 52-week data is never backfilled "
            "into historical matches."
        ),
    )
    parser.add_argument(
        "--atp-rank-history-sqlite",
        default="",
        help=(
            "Pinned weekly ATP ranking SQLite archive. Historical features use "
            "only snapshots strictly before each match date."
        ),
    )
    parser.add_argument(
        "--wta-season-stats-csv",
        default="",
        help=(
            "Verified WTA seasonal serve/return CSV. Historical rows use only "
            "the previous completed season to prevent same-season leakage."
        ),
    )
    args = parser.parse_args()

    matches, identity_safety = sanitize_history_identities(load_partitions(Path(args.history_dir)))
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

    atp_feature_rows = []
    if args.atp_leaderboards_csv:
        priors = ATPLeaderboardPriors.from_csv(args.atp_leaderboards_csv)
        for match_id in frame["match_id"]:
            original = source[match_id]
            oriented, _ = FeatureBuilder.orient_for_training(original)
            atp_feature_rows.append(
                priors.features_for_match(oriented, current=False)
            )
    else:
        atp_feature_rows = [
            {name: 0.0 for name in ATP_LEADERBOARD_FEATURE_NAMES}
            for _ in range(len(frame))
        ]

    for name in ATP_LEADERBOARD_FEATURE_NAMES:
        frame[name] = [float(row.get(name, 0.0)) for row in atp_feature_rows]

    atp_coverage = atp_coverage_summary(atp_feature_rows)

    atp_rank_history_rows = []
    if args.atp_rank_history_sqlite:
        rank_history = ATPRankHistory.from_sqlite(args.atp_rank_history_sqlite)
        for match_id in frame["match_id"]:
            original = source[match_id]
            oriented, _ = FeatureBuilder.orient_for_training(original)
            atp_rank_history_rows.append(rank_history.features_for_match(oriented))
    else:
        atp_rank_history_rows = [
            {name: 0.0 for name in ATP_RANK_HISTORY_FEATURE_NAMES}
            for _ in range(len(frame))
        ]

    for name in ATP_RANK_HISTORY_FEATURE_NAMES:
        frame[name] = [float(row.get(name, 0.0)) for row in atp_rank_history_rows]

    atp_rank_history_coverage = atp_rank_history_coverage_summary(
        atp_rank_history_rows
    )

    wta_feature_rows = []
    if args.wta_season_stats_csv:
        wta_priors = WTASeasonPriors.from_csv(args.wta_season_stats_csv)
        for match_id in frame["match_id"]:
            original = source[match_id]
            oriented, _ = FeatureBuilder.orient_for_training(original)
            wta_feature_rows.append(
                wta_priors.features_for_match(oriented, current=False)
            )
    else:
        wta_feature_rows = [
            {name: 0.0 for name in WTA_SEASON_FEATURE_NAMES}
            for _ in range(len(frame))
        ]

    for name in WTA_SEASON_FEATURE_NAMES:
        frame[name] = [float(row.get(name, 0.0)) for row in wta_feature_rows]

    wta_coverage = wta_coverage_summary(wta_feature_rows)

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False, engine="pyarrow")

    report = build_report(frame, quality, rank_provenance)
    report["atp_leaderboards"] = {
        **atp_coverage,
        "training_eligible": True,
        "production_enabled": False,
        "features": list(ATP_LEADERBOARD_FEATURE_NAMES),
        "historical_policy": "previous_completed_season_only",
        "current_policy": "rolling_52week",
        "surface_policy": "exact_surface_plus_all_surface_baseline",
        "identity_policy": "unique_normalized_name_or_unique_first_initial_surname",
        "source_csv": str(args.atp_leaderboards_csv or ""),
    }
    report.setdefault("candidate_feature_groups", {})["atp_leaderboard_priors"] = {
        "schema_eligible": True,
        "has_observations": bool(atp_coverage.get("known_both_rate", 0.0)),
        "eligible_for_candidate": bool(atp_coverage.get("known_both_rate", 0.0)),
        "production_enabled": False,
        "coverage": atp_coverage.get("known_both_rate", 0.0),
        "surface_coverage": atp_coverage.get("surface_known_both_rate", 0.0),
        "features": list(ATP_LEADERBOARD_FEATURE_NAMES),
        "reason": "requires chronological ablation before production feature activation",
    }
    report["atp_rank_history"] = {
        **atp_rank_history_coverage,
        "training_eligible": True,
        "production_enabled": False,
        "features": list(ATP_RANK_HISTORY_FEATURE_NAMES),
        "historical_policy": "latest_weekly_snapshot_strictly_before_match_date",
        "source_sqlite": str(args.atp_rank_history_sqlite or ""),
    }
    report.setdefault("candidate_feature_groups", {})["atp_rank_history"] = {
        "schema_eligible": True,
        "has_observations": bool(
            atp_rank_history_coverage.get("known_both_rate", 0.0)
        ),
        "eligible_for_candidate": bool(
            atp_rank_history_coverage.get("known_both_rate", 0.0)
        ),
        "production_enabled": False,
        "coverage": atp_rank_history_coverage.get("known_both_rate", 0.0),
        "momentum_4w_coverage": atp_rank_history_coverage.get(
            "momentum_4w_known_both_rate", 0.0
        ),
        "momentum_12w_coverage": atp_rank_history_coverage.get(
            "momentum_12w_known_both_rate", 0.0
        ),
        "features": list(ATP_RANK_HISTORY_FEATURE_NAMES),
        "reason": "requires chronological ablation before production activation",
    }
    report["wta_season_stats"] = {
        **wta_coverage,
        "training_eligible": True,
        "production_enabled": False,
        "features": list(WTA_SEASON_FEATURE_NAMES),
        "historical_policy": "previous_completed_season_only",
        "identity_policy": "unique_normalized_name_or_unique_first_initial_surname",
        "source_csv": str(args.wta_season_stats_csv or ""),
    }
    report.setdefault("candidate_feature_groups", {})["wta_season_priors"] = {
        "schema_eligible": True,
        "has_observations": bool(wta_coverage.get("known_both_rate", 0.0)),
        "eligible_for_candidate": bool(wta_coverage.get("known_both_rate", 0.0)),
        "production_enabled": False,
        "coverage": wta_coverage.get("known_both_rate", 0.0),
        "features": list(WTA_SEASON_FEATURE_NAMES),
        "reason": "requires chronological ablation before production feature activation",
    }
    report["identity_safety"] = identity_safety
    report["output"] = str(out)
    report_path = Path(args.report); report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
