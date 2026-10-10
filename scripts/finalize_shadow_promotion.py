"""Finalize BlinQ model promotion from the already-captured shadow cohort.

This intentionally does NOT retrain a model and does NOT call any provider API.
It evaluates the exact shadow-tested candidate against production and
point-in-time Elo on one verified fixture, but NEVER writes a model release.
Production promotion requires separate explicit operator approval and a
verified isolated champion rollback rehearsal (issue #405).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from download_tennis_history import read_json, write_json
from pipeline import _promotion_metric_gate, _promotion_history, _holdout_already_used
from release_store import ReleaseStore
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.models.artifact import load_model
from tbt.models.elo import elo_expected, update_elo
from tbt.models.feature_builder import FeatureBuilder, PlayerState, stats_surface_key
from tbt.models.metrics import evaluate_probabilities
from tbt.services.data_quality import audit_history


REQUIRED_MIN_MATCHES = 200
REQUIRED_MIN_DAYS = 3
REQUIRED_MIN_TOUR_MATCHES = 50


def _clean_float(value):
    if value is None:
        return None
    return float(value)


def _metric_delta(left: dict, right: dict, key: str):
    lv = left.get(key)
    rv = right.get(key)
    if lv is None or rv is None:
        return None
    return float(lv) - float(rv)


def _tour_metrics(rows, probability_key: str) -> dict:
    result = {}
    for tour in ("atp", "wta"):
        selected = [row for row in rows if str(row.get("tour") or "").lower() == tour]
        y = [int(row["target_player1_win"]) for row in selected]
        p = [float(row[probability_key]) for row in selected]
        result[tour] = evaluate_probabilities(y, p) if y else {"n": 0}
    return result


def _fingerprint(rows, production_version: str, candidate_version: str) -> str:
    payload = {
        "policy": "shadow_same_fixture_plus_point_in_time_elo_v1",
        "production_version": production_version,
        "candidate_version": candidate_version,
        "match_ids": sorted(str(row["match_id"]) for row in rows),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _level_multiplier(level: str) -> float:
    return 1.0 + 0.15 * FeatureBuilder._level_value(level)


def _elo_probability_for_match(states: dict[str, PlayerState], match) -> float:
    p1 = states[match.player1_id]
    p2 = states[match.player2_id]
    surface = stats_surface_key(match.surface)
    s1 = p1.get_surface_elo(surface)
    s2 = p2.get_surface_elo(surface)
    blended1 = 0.48 * p1.overall_elo + 0.52 * s1
    blended2 = 0.48 * p2.overall_elo + 0.52 * s2
    return float(elo_expected(blended1, blended2))


def _update_elo_state(states: dict[str, PlayerState], match) -> None:
    p1 = states[match.player1_id]
    p2 = states[match.player2_id]
    p1_won = float(match.winner_id == match.player1_id)

    new1, new2 = update_elo(
        p1.overall_elo,
        p2.overall_elo,
        p1_won,
        p1.matches,
        p2.matches,
        multiplier=_level_multiplier(match.tournament_level),
    )

    surface = stats_surface_key(match.surface)
    if surface != "unknown":
        old_s1 = p1.surface_elo.get(surface, p1.overall_elo)
        old_s2 = p2.surface_elo.get(surface, p2.overall_elo)
        sm1 = p1.surface_matches.get(surface, 0)
        sm2 = p2.surface_matches.get(surface, 0)
        ns1, ns2 = update_elo(
            old_s1,
            old_s2,
            p1_won,
            sm1,
            sm2,
            multiplier=0.9,
        )
        p1.surface_elo[surface] = ns1
        p2.surface_elo[surface] = ns2
        p1.surface_matches[surface] = sm1 + 1
        p2.surface_matches[surface] = sm2 + 1

    p1.overall_elo = new1
    p2.overall_elo = new2
    p1.matches += 1
    p2.matches += 1


def _attach_point_in_time_elo(rows: list[dict], matches) -> tuple[list[dict], dict]:
    """Replay only Elo state over canonical history and annotate target shadow rows.

    This mirrors FeatureBuilder's same-day snapshot policy and exact overall /
    surface Elo equations, but avoids rebuilding the full training feature frame.
    """
    target = {str(row["match_id"]): row for row in rows}
    if len(target) != len(rows):
        raise ValueError("Duplicate match_id inside active shadow cohort")

    states: dict[str, PlayerState] = defaultdict(PlayerState)
    accepted, quality = audit_history(matches)
    accepted = sorted(accepted, key=lambda m: (m.scheduled_at, m.match_id))

    found = set()
    current_day = None
    batch = []

    def process(day_matches):
        for match in day_matches:
            key = str(match.match_id)
            row = target.get(key)
            if row is None:
                continue
            p = _elo_probability_for_match(states, match)
            ledger_p1 = str(row.get("player1_id") or "")
            ledger_p2 = str(row.get("player2_id") or "")
            canonical_p1 = str(match.player1_id)
            canonical_p2 = str(match.player2_id)
            if ledger_p1 == canonical_p1 and ledger_p2 == canonical_p2:
                row["elo_player1_probability"] = p
            elif ledger_p1 == canonical_p2 and ledger_p2 == canonical_p1:
                row["elo_player1_probability"] = 1.0 - p
            else:
                raise ValueError(
                    f"Shadow/canonical player identity mismatch for match {key}"
                )
            found.add(key)
        for match in day_matches:
            _update_elo_state(states, match)

    for match in accepted:
        day = match.scheduled_at.astimezone(timezone.utc).date()
        if current_day is None:
            current_day = day
        if day != current_day:
            process(batch)
            batch = []
            current_day = day
        batch.append(match)
    if batch:
        process(batch)

    missing = sorted(set(target) - found)
    if missing:
        raise ValueError(
            f"Active shadow cohort contains {len(missing)} match IDs absent from canonical history"
        )

    return rows, quality


def _period(rows: list[dict]) -> dict:
    values = sorted(str(row.get("scheduled_at") or "") for row in rows if row.get("scheduled_at"))
    return {
        "start": values[0] if values else None,
        "end": values[-1] if values else None,
    }


def _build_gate_report(rows: list[dict], production_version: str, candidate_version: str, *, as_of=None) -> dict:
    y = [int(row["target_player1_win"]) for row in rows]
    candidate_p = [float(row["challenger_player1_probability"]) for row in rows]
    production_p = [float(row["production_player1_probability"]) for row in rows]
    elo_p = [float(row["elo_player1_probability"]) for row in rows]

    candidate = evaluate_probabilities(y, candidate_p)
    production = evaluate_probabilities(y, production_p)
    elo = evaluate_probabilities(y, elo_p)

    delta_vs_elo = {
        key: _metric_delta(candidate, elo, key)
        for key in ("accuracy", "roc_auc", "log_loss", "brier_score", "ece_10")
    }
    delta_vs_production = {
        key: _metric_delta(candidate, production, key)
        for key in ("accuracy", "roc_auc", "log_loss", "brier_score", "ece_10")
    }

    days = {
        str(row.get("scheduled_at") or "")[:10]
        for row in rows
        if row.get("scheduled_at")
    }
    by_tour = {
        tour: sum(str(row.get("tour") or "").lower() == tour for row in rows)
        for tour in ("atp", "wta")
    }

    reasons = []
    clock = as_of if as_of is not None else datetime.now(timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("Shadow gate cutoff must be timezone-aware")
    today_utc = clock.astimezone(timezone.utc).date()
    # Never promote from a cohort containing the current or a future UTC date.
    # Reject the *entire* mixed cohort rather than silently changing its fingerprint.
    if any(day >= today_utc.isoformat() for day in days):
        reasons.append("shadow_holdout_contains_incomplete_utc_day")
    if len(rows) < REQUIRED_MIN_MATCHES:
        reasons.append("shadow_holdout_n_below_200")
    if len(days) < REQUIRED_MIN_DAYS:
        reasons.append("shadow_holdout_days_below_3")
    for tour in ("atp", "wta"):
        if by_tour[tour] < REQUIRED_MIN_TOUR_MATCHES:
            reasons.append(f"{tour}_shadow_sample_below_50")

    return {
        "schema": 1,
        "evaluation_governance": {
            "holdout_fingerprint": _fingerprint(rows, production_version, candidate_version),
            "promotion_reference": "shadow_same_fixture_plus_point_in_time_elo",
            "production_version": production_version,
            "candidate_version": candidate_version,
            "production_present": True,
            "eligibility_reason": reasons[0] if reasons else None,
            "eligibility_reasons": reasons,
            "same_fixture_pre_match_probabilities": True,
            "elo_policy": "exact FeatureBuilder overall+surface Elo replay; same-day snapshots before results",
        },
        "periods": {"holdout": _period(rows)},
        "holdout": candidate,
        "elo_baseline_holdout": elo,
        "delta_vs_elo": delta_vs_elo,
        "production_holdout": production,
        "delta_vs_production": delta_vs_production,
        "subgroups": {"tour": _tour_metrics(rows, "challenger_player1_probability")},
        "production_subgroups": {"tour": _tour_metrics(rows, "production_player1_probability")},
        "shadow": {
            "settled": len(rows),
            "settled_utc_days": len(days),
            "by_tour": by_tour,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-repository", required=True)
    parser.add_argument("--out", default=".cache/tbt/shadow-promotion/final_report.json")
    args = parser.parse_args()

    root = Path(".cache/tbt/shadow-promotion")
    history_dir = root / "history"
    candidate_dir = root / "candidate"
    production_dir = root / "production"
    shadow_dir = root / "shadow"
    for path in (history_dir, candidate_dir, production_dir, shadow_dir):
        path.mkdir(parents=True, exist_ok=True)

    candidate = ReleaseStore(args.data_repository, "tbt-model-candidate-v1", candidate_dir)
    candidate.download(
        extra_names=("model.joblib", "training_report.json", "promotion_history.json"),
        required_names=("model.joblib", "training_report.json", "promotion_history.json"),
    )
    production = ReleaseStore(args.data_repository, "tbt-model-production-v1", production_dir)
    production.download(
        extra_names=("model.joblib", "training_report.json", "promotion_history.json"),
        required_names=("model.joblib", "training_report.json", "promotion_history.json"),
    )
    shadow = ReleaseStore(args.data_repository, "tbt-model-shadow-v1", shadow_dir)
    shadow.download(
        extra_names=("shadow_ledger.json", "shadow_report.json"),
        required_names=("shadow_ledger.json", "shadow_report.json"),
    )

    candidate_model = load_model(str(candidate_dir / "model.joblib"))
    production_model = load_model(str(production_dir / "model.joblib"))
    candidate_version = str(candidate_model.version)
    production_version = str(production_model.version)

    if candidate_version == production_version:
        report = {
            "schema": 1,
            "status": "already_production",
            "candidate_version": candidate_version,
            "production_version": production_version,
            "provider_requests": 0,
            "retrained": False,
        }
        write_json(Path(args.out), report)
        print(json.dumps(report, indent=2))
        return

    ledger = read_json(shadow_dir / "shadow_ledger.json", [])
    if not isinstance(ledger, list):
        raise ValueError("Invalid shadow ledger")

    rows = [
        dict(row)
        for row in ledger
        if isinstance(row, dict)
        and row.get("status") == "settled"
        and str(row.get("production_model_version") or "") == production_version
        and str(row.get("challenger_model_version") or "") == candidate_version
    ]
    rows.sort(key=lambda row: (str(row.get("scheduled_at") or ""), str(row.get("match_id") or "")))
    if not rows:
        raise ValueError(
            "No settled shadow rows for the exact current production/candidate pair"
        )

    history_store = ReleaseStore(args.data_repository, "tbt-data-v1", history_dir)
    history_store.download(require_bundle_manifest=True)
    matches, identity = sanitize_history_identities(load_partitions(history_dir))
    if identity.get("quarantined_rows"):
        raise ValueError("Canonical identity quarantine is non-empty")

    rows, history_quality = _attach_point_in_time_elo(rows, matches)
    gate_report = _build_gate_report(rows, production_version, candidate_version)
    fingerprint = gate_report["evaluation_governance"]["holdout_fingerprint"]

    candidate_history = _promotion_history(candidate_dir / "promotion_history.json")
    production_history = _promotion_history(production_dir / "promotion_history.json")
    merged_history = list(candidate_history)
    for decision in production_history:
        if decision not in merged_history:
            merged_history.append(decision)

    if _holdout_already_used(merged_history, fingerprint):
        raise ValueError("This exact shadow evaluation cohort was already consumed")

    eligible, gate_reasons = _promotion_metric_gate(gate_report)
    extra_reasons = gate_report["evaluation_governance"].get("eligibility_reasons") or []
    for reason in extra_reasons:
        if reason not in gate_reasons:
            gate_reasons.append(reason)
    eligible = eligible and not extra_reasons

    decision = {
        "holdout_fingerprint": fingerprint,
        "candidate_version": candidate_version,
        "production_version": production_version,
        "decided_at": __import__("datetime").datetime.now(timezone.utc).isoformat(),
        "reference": "shadow_same_fixture_plus_point_in_time_elo",
        "holdout_period": gate_report["periods"]["holdout"],
        "holdout_metrics": gate_report["holdout"],
        "production_metrics": gate_report["production_holdout"],
        "elo_metrics": gate_report["elo_baseline_holdout"],
        "delta_vs_elo": gate_report["delta_vs_elo"],
        "delta_vs_production": gate_report["delta_vs_production"],
        "eligible": bool(eligible),
        "promotion_requested": False,
        "decision": "eligible_pending_approval" if eligible else "rejected",
        "reasons": gate_reasons,
        "shadow": gate_report["shadow"],
        "artifact_policy": "promote exact shadow-tested candidate; no refit",
    }
    # No candidate or production release write is permitted by this gate.
    # A favorable result is research evidence, NOT authorization to promote.
    status = "eligible_pending_approval" if eligible else "rejected"

    final = {
        "schema": 1,
        "status": status,
        "candidate_version": candidate_version,
        "previous_production_version": production_version,
        "production_version_after": production_version,
        "decision": decision,
        "gate_report": gate_report,
        "canonical_identity": identity,
        "canonical_history_quality": history_quality,
        "provider_requests": 0,
        "retrained": False,
        "canonical_mutated": False,
        "exact_shadow_tested_artifact_promoted": False,
        "operator_approval_required": bool(eligible),
        "production_release_mutated": False,
        "candidate_release_mutated": False,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, final)
    print(json.dumps(final, indent=2))


if __name__ == "__main__":
    main()
