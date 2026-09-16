"""Combine production preflight reports into one actionable readiness summary.

Coverage thresholds in this report are data-readiness gates only; they are not
model-quality or promotion gates. Leakage failures and an empty training table are
blockers. Promotion still requires the later chronological holdout/backtest gate.
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
    presentation_warnings: list[str] = []
    model_warnings: list[str] = []
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

    es_rate = float(sc.get("stats_known_both_rate") or 0)
    env_rate = float(ec.get("venue_environment_known_rate") or 0)
    es_min = float(es_group.get("min_coverage") or sc.get("readiness_min_coverage") or 0.70)
    env_min = float(env_group.get("min_coverage") or ec.get("readiness_min_coverage") or 0.80)

    def explicit_ready(group: dict, section: dict, rate: float, threshold: float) -> bool:
        if "ready_for_candidate_eval" in group:
            return bool(group.get("ready_for_candidate_eval"))
        if "ready_for_candidate_eval" in section:
            return bool(section.get("ready_for_candidate_eval"))
        return rate >= threshold

    es_ready = explicit_ready(es_group, sc, es_rate, es_min)
    env_ready = explicit_ready(env_group, ec, env_rate, env_min)

    def preferred(match_weighted_key: str, entity_value: Any) -> float:
        weighted = mw.get(match_weighted_key)
        try:
            if weighted is not None:
                return float(weighted)
            return float(entity_value or 0)
        except (TypeError, ValueError):
            return 0.0

    effective_tournament_country = preferred("country", tv.get("country"))
    effective_venue_coordinates = preferred("coordinates", vv.get("coordinates"))
    effective_venue_elevation = preferred("elevation", vv.get("elevation"))

    # Player-master country/rank are presentation/identity diagnostics. They do
    # not certify point-in-time training ranks and therefore never make the model
    # candidate-ready by themselves.
    if pc < 0.98:
        presentation_warnings.append("player_country_coverage_below_98pct")
    if rc < 0.90:
        presentation_warnings.append("player_rank_coverage_below_90pct")
    if effective_tournament_country < 0.95:
        model_warnings.append("match_weighted_tournament_country_coverage_below_95pct")
    if effective_venue_coordinates < 0.90:
        model_warnings.append("match_weighted_venue_coordinate_coverage_below_90pct")
    if effective_venue_elevation < 0.80:
        model_warnings.append("match_weighted_venue_elevation_coverage_below_80pct")
    if env_rate < env_min:
        model_warnings.append("static_environment_match_coverage_below_readiness_gate")
    if not env_ready:
        model_warnings.append("static_environment_not_ready_for_candidate_eval")
    if es_rate < es_min:
        model_warnings.append("event_statistics_match_coverage_below_readiness_gate")
    if not es_ready:
        model_warnings.append("event_statistics_not_ready_for_candidate_eval")

    raw_rate = float(statistics.get("any_stats_rate", sc.get("raw_statistics_match_rate") or 0) or 0)
    quality_capable_rate = float(statistics.get("quality_capable_rate") or 0)
    both_quality_rate = float(statistics.get("both_players_quality_ready_rate", es_rate) or 0)
    ace_df_only_share = float(statistics.get("ace_df_only_share_of_stats") or 0)
    if raw_rate > 0 and both_quality_rate < es_min:
        model_warnings.append("raw_statistics_present_but_es_quality_insufficient")

    duplicate_groups = int(((tournament.get("identity_diagnostics") or {}).get("potential_duplicate_signature_groups") or 0))
    if duplicate_groups:
        presentation_warnings.append("potential_duplicate_tournament_identities_require_review")
    if int(player.get("duplicate_name_groups") or 0):
        presentation_warnings.append("duplicate_player_names_require_identity_review")

    warnings.extend(model_warnings)
    warnings.extend(presentation_warnings)

    recommended_sequence: list[str] = []
    if blockers:
        recommended_sequence.append("resolve-preflight-blockers")
    else:
        if not env_ready:
            recommended_sequence.append("environment-static")
        if not es_ready:
            if quality_capable_rate > 0:
                recommended_sequence.append("statistics")
            elif raw_rate > 0:
                recommended_sequence.append("review-statistics-inventory-before-statistics-enrichment")
            else:
                recommended_sequence.append("statistics-coverage-investigation")
        if not env_ready or not es_ready:
            recommended_sequence.append("production-preflight")
        else:
            recommended_sequence.extend(["train", "backtest-ablation", "promotion-gate"])

    return {
        "schema": 2,
        "status": "blocked" if blockers else ("ready_with_warnings" if warnings else "ready"),
        "blockers": blockers,
        "warnings": warnings,
        "warning_groups": {
            "model_data": model_warnings,
            "presentation_identity": presentation_warnings,
        },
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
            "static_environment_matches": env_rate,
            "event_statistics_both_players": es_rate,
            "raw_statistics_matches": raw_rate,
            "statistics_quality_capable_matches": quality_capable_rate,
        },
        "readiness_gates": {
            "event_statistics_min_coverage": es_min,
            "static_environment_min_coverage": env_min,
            "event_statistics_observed": bool(es_group.get("has_observations", sc.get("has_observations", es_rate > 0))),
            "static_environment_observed": bool(env_group.get("has_observations", ec.get("has_observations", env_rate > 0))),
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
            "any_stats_rate": raw_rate,
            "quality_capable_rate": quality_capable_rate,
            "both_players_quality_ready_rate": both_quality_rate,
            "ace_df_only_share_of_stats": ace_df_only_share,
            "top_stat_keys": list((statistics.get("stat_key_counts") or {}).items())[:20],
        },
        "recommended_sequence": recommended_sequence,
        "next_actions": [
            "resolve leakage/data blockers first" if blockers else "finish enrichment groups that are below their data-readiness gates",
            "treat all-time player profile coverage as presentation diagnostics, not historical rank provenance",
            "use match-weighted tournament/venue geography for model-readiness decisions",
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
        "statistics_quality_capable_matches": "Rows with at least one ES-capable signal",
    }
    lines += [f"| {labels[k]} | {_pct(c.get(k))} |" for k in labels]
    lines += ["", "## Blockers"]
    lines += [f"- {x}" for x in report.get("blockers") or []] or ["- none"]
    lines += ["", "## Warnings"]
    lines += [f"- {x}" for x in report.get("warnings") or []] or ["- none"]
    gates = report.get("readiness_gates") or {}
    lines += [
        "", "## Data-readiness gates", "",
        f"- ES minimum coverage: {_pct(gates.get('event_statistics_min_coverage'))}",
        f"- Static environment minimum coverage: {_pct(gates.get('static_environment_min_coverage'))}",
    ]
    candidate = report.get("candidate_training") or {}
    lines += [
        "", "## Candidate feature policy", "",
        f"- ES: {'ready' if candidate.get('event_statistics') else '**not ready**'}",
        f"- Static environment: {'ready' if candidate.get('static_environment') else '**not ready**'}",
        "- Historical/post-hoc weather: **not eligible**", "",
        "## Recommended sequence", "",
    ]
    lines += [f"- {x}" for x in report.get("recommended_sequence") or []] or ["- none"]
    lines.append("")
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
