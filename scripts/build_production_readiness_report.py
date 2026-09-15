"""Combine production preflight reports into one actionable readiness summary.

This script does not invent hard model-quality thresholds. Leakage failures and an
empty training table are blockers; incomplete enrichment coverage is surfaced as
warnings for human review before retraining/promotion.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {}
    value = json.loads(p.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def build(player: dict, tournament: dict, training: dict, leakage: dict, statistics: dict | None = None) -> dict[str, Any]:
    statistics = statistics or {}
    blockers: list[str] = []
    warnings: list[str] = []
    if leakage.get("status") != "pass":
        blockers.append("leakage_audit_failed")
    if int(training.get("rows") or 0) <= 0:
        blockers.append("training_table_empty")

    pc = float(player.get("country_coverage") or 0)
    rc = float(player.get("latest_rank_coverage") or 0)
    tv = tournament.get("tournament_coverage") or {}
    vv = tournament.get("venue_coverage") or {}
    sc = training.get("event_statistics") or {}
    ec = training.get("static_environment") or {}
    mw = tournament.get("match_weighted_coverage") or {}
    candidate_groups = training.get("candidate_feature_groups") or {}
    es_group = candidate_groups.get("event_statistics") or {}
    env_group = candidate_groups.get("static_environment") or {}
    es_ready = bool(es_group.get("ready_for_candidate_eval", sc.get("ready_for_candidate_eval", float(sc.get("stats_known_both_rate") or 0) > 0)))
    env_ready = bool(env_group.get("ready_for_candidate_eval", ec.get("ready_for_candidate_eval", float(ec.get("venue_environment_known_rate") or 0) > 0)))

    if pc < 0.98:
        warnings.append("player_country_coverage_below_98pct")
    if rc < 0.90:
        warnings.append("player_rank_coverage_below_90pct")
    if float(tv.get("country") or 0) < 0.95:
        warnings.append("tournament_country_coverage_below_95pct")
    if float(vv.get("coordinates") or 0) < 0.90:
        warnings.append("venue_coordinate_coverage_below_90pct")
    if float(vv.get("elevation") or 0) < 0.80:
        warnings.append("venue_elevation_coverage_below_80pct")
    if float(ec.get("venue_environment_known_rate") or 0) < 0.80:
        warnings.append("static_environment_match_coverage_below_80pct")
    if not es_ready:
        warnings.append("event_statistics_not_ready_for_candidate_eval")
    elif float(sc.get("stats_known_both_rate") or 0) < 0.70:
        warnings.append("event_statistics_match_coverage_below_70pct")
    if not env_ready:
        warnings.append("static_environment_not_ready_for_candidate_eval")

    duplicate_groups = int(((tournament.get("identity_diagnostics") or {}).get("potential_duplicate_signature_groups") or 0))
    if duplicate_groups:
        warnings.append("potential_duplicate_tournament_identities_require_review")
    if int(player.get("duplicate_name_groups") or 0):
        warnings.append("duplicate_player_names_require_identity_review")

    return {
        "schema": 1,
        "status": "blocked" if blockers else ("ready_with_warnings" if warnings else "ready"),
        "blockers": blockers,
        "warnings": warnings,
        "coverage": {
            "player_country": pc,
            "player_latest_rank": rc,
            "tournament_country": tv.get("country"),
            "tournament_city": tv.get("city"),
            "venue_coordinates": vv.get("coordinates"),
            "venue_elevation": vv.get("elevation"),
            "venue_timezone": vv.get("timezone"),
            "match_weighted_tournament_country": mw.get("country"),
            "match_weighted_tournament_city": mw.get("city"),
            "match_weighted_venue_coordinates": mw.get("coordinates"),
            "match_weighted_venue_elevation": mw.get("elevation"),
            "match_weighted_venue_timezone": mw.get("timezone"),
            "static_environment_matches": ec.get("venue_environment_known_rate"),
            "event_statistics_both_players": sc.get("stats_known_both_rate"),
            "raw_statistics_matches": sc.get("raw_statistics_match_rate", statistics.get("any_stats_rate")),
        },
        "counts": {
            "players": player.get("players"),
            "tournaments": tournament.get("tournaments"),
            "venues": tournament.get("venues"),
            "training_rows": training.get("rows"),
            "potential_duplicate_tournament_groups": duplicate_groups,
            "duplicate_player_name_groups": player.get("duplicate_name_groups"),
        },
        "candidate_training": {
            "event_statistics": es_ready,
            "static_environment": env_ready,
            "historical_weather": False,
            "historical_weather_reason": "requires genuine point-in-time pre-match forecast snapshots",
        },
        "statistics_diagnostics": {
            "any_stats_rate": statistics.get("any_stats_rate", sc.get("raw_statistics_match_rate")),
            "both_players_quality_ready_rate": statistics.get("both_players_quality_ready_rate", sc.get("stats_known_both_rate")),
            "top_stat_keys": list((statistics.get("stat_key_counts") or {}).items())[:20],
        },
        "next_actions": [
            "review identity/coverage warnings; no leakage blocker is present" if not blockers else "resolve leakage/data blockers first",
            "backfill or redesign ES only if both-player serve+return quality is actually available",
            "complete recent static-environment enrichment before final candidate comparison",
            "retrain only feature groups marked ready_for_candidate_eval",
            "run chronological holdout/backtest + ablation",
            "promote only if candidate gate passes",
        ],
    }


def markdown(report: dict[str, Any]) -> str:
    c = report.get("coverage") or {}
    lines = [
        "# BlinQ production data readiness",
        "",
        f"**Status:** `{report.get('status')}`",
        "",
        "## Coverage",
        "",
        "| Metric | Coverage |",
        "|---|---:|",
    ]
    labels = {
        "player_country": "Player country / flags",
        "player_latest_rank": "Player latest rank",
        "tournament_country": "Tournament country",
        "tournament_city": "Tournament city",
        "venue_coordinates": "Venue coordinates",
        "venue_elevation": "Venue elevation",
        "venue_timezone": "Venue timezone (unique entities)",
        "match_weighted_tournament_country": "Tournament country (match-weighted)",
        "match_weighted_tournament_city": "Tournament city (match-weighted)",
        "match_weighted_venue_coordinates": "Venue coordinates (match-weighted)",
        "match_weighted_venue_elevation": "Venue elevation (match-weighted)",
        "match_weighted_venue_timezone": "Venue timezone (match-weighted)",
        "static_environment_matches": "Static environment in training rows",
        "event_statistics_both_players": "ES for both players in training rows",
        "raw_statistics_matches": "Rows carrying any raw statistics",
    }
    lines += [f"| {labels[k]} | {_pct(c.get(k))} |" for k in labels]
    lines += ["", "## Blockers"]
    lines += [f"- {x}" for x in report.get("blockers") or []] or ["- none"]
    lines += ["", "## Warnings"]
    lines += [f"- {x}" for x in report.get("warnings") or []] or ["- none"]
    candidate = report.get("candidate_training") or {}
    lines += [
        "", "## Candidate feature policy", "",
        f"- ES: {'ready' if candidate.get('event_statistics') else '**not ready**'}",
        f"- Static environment: {'ready' if candidate.get('static_environment') else '**not ready**'}",
        "- Historical/post-hoc weather: **not eligible**", "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--player-report", required=True)
    ap.add_argument("--tournament-report", required=True)
    ap.add_argument("--training-report", required=True)
    ap.add_argument("--leakage-report", required=True)
    ap.add_argument("--statistics-report", default="")
    ap.add_argument("--out", default=".cache/tbt/production/readiness_report.json")
    ap.add_argument("--markdown", default=".cache/tbt/production/readiness_report.md")
    args = ap.parse_args()
    report = build(
        _load(args.player_report), _load(args.tournament_report),
        _load(args.training_report), _load(args.leakage_report),
        _load(args.statistics_report) if args.statistics_report else {},
    )
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = Path(args.markdown); md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == "blocked":
        raise SystemExit("Production data preflight blocked: " + ", ".join(report["blockers"]))


if __name__ == "__main__":
    main()
