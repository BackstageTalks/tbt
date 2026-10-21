"""Strict, read-only provenance gate for the immutable v7.2.1 shadow cohort.

The candidate's aggregate holdout is not per-match evidence. The existing
tbt-model-shadow-v1 cohort belongs to a different challenger; never mix them.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math

from .shadow_calibration_research import research_comparison

FROZEN_721_TAG = "blinq-candidate-frozen-39368300257-1"
FROZEN_721_VERSION = "v7.2.1-v201-20261020T061347180376Z"
FROZEN_721_MODEL_SHA256 = "2296165e9407a8ec83890bf3c3e18a81b951504bdf0dc8cb3ae8237ea80c9202"


def _utc(value, field):
    if not value:
        raise ValueError(f"missing_{field}")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_{field}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"naive_{field}")
    return parsed.astimezone(timezone.utc)


def _probability(value, field):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_{field}") from exc
    if not math.isfinite(value) or not 0 < value < 1:
        raise ValueError(f"invalid_{field}")


def validate_frozen_evidence(payload, *, production_version):
    """Require correctly pinned, pre-match paired evidence, not a legacy shadow."""
    if not isinstance(payload, dict):
        raise ValueError("invalid_evidence_payload")
    source = payload.get("source")
    if not isinstance(source, dict):
        raise ValueError("missing_frozen_source_provenance")
    if (source.get("candidate_tag") != FROZEN_721_TAG
            or source.get("candidate_version") != FROZEN_721_VERSION
            or source.get("candidate_model_sha256") != FROZEN_721_MODEL_SHA256):
        raise ValueError("wrong_frozen_721_artifact")
    if not production_version or source.get("production_version") != production_version:
        raise ValueError("wrong_production_model_pair")
    if source.get("provider_requests") != 0:
        raise ValueError("evidence_must_not_spend_provider_requests")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("missing_paired_prediction_rows")
    seen = set()
    counts = {"pending": 0, "settled": 0, "void": 0, "excluded": 0}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid_shadow_row")
        if (row.get("production_model_version") != production_version
                or row.get("challenger_model_version") != FROZEN_721_VERSION):
            raise ValueError("foreign_model_pair_in_frozen_cohort")
        match_id = str(row.get("match_id") or "").strip()
        p1 = str(row.get("player1_id") or "").strip()
        p2 = str(row.get("player2_id") or "").strip()
        if not match_id or not p1 or not p2 or p1 == p2:
            raise ValueError("missing_or_ambiguous_match_identity")
        if match_id in seen:
            raise ValueError("duplicate_match_id_in_frozen_cohort")
        seen.add(match_id)
        if str(row.get("tour") or "").upper() not in {"ATP", "WTA"}:
            raise ValueError("unknown_tour")
        capture = _utc(row.get("captured_at"), "captured_at")
        scheduled = _utc(row.get("scheduled_at"), "scheduled_at")
        if capture >= scheduled:
            raise ValueError("prediction_not_captured_before_match")
        _probability(row.get("production_player1_probability"), "production_probability")
        _probability(row.get("challenger_player1_probability"), "challenger_probability")
        status = row.get("status")
        if status not in counts:
            raise ValueError("unknown_shadow_status")
        counts[status] += 1
        if status == "settled":
            settled = _utc(row.get("settled_at"), "settled_at")
            if settled <= scheduled or settled <= capture:
                raise ValueError("settlement_not_after_fixture")
            winner = str(row.get("result_winner_id") or "").strip()
            if winner not in (p1, p2):
                raise ValueError("settled_winner_identity_mismatch")
            truth = row.get("target_player1_win")
            if type(truth) is not int or truth != int(winner == p1):
                raise ValueError("settled_target_identity_mismatch")
        elif row.get("target_player1_win") is not None:
            raise ValueError("outcome_leaked_into_unsettled_row")
    return rows, counts


def exclude_repeated_events(rows):
    """Keep the earliest snapshot per provider event, retaining all audit rows.

    Schedule changes can generate new internal match hashes for the same event.
    Never select a later prediction by its probability or eventual result.
    """
    result = [dict(row) for row in rows]
    groups = {}
    for row in result:
        event = str(row.get("event_id") or "").strip()
        if event:
            groups.setdefault(event, []).append(row)
    for group in groups.values():
        if len(group) < 2:
            continue
        identities = {(str(r["tour"]).upper(), frozenset((r["player1_id"], r["player2_id"])),
                       r["production_model_version"], r["challenger_model_version"]) for r in group}
        if len(identities) != 1:
            raise ValueError("Conflicting provider event identities in frozen cohort")
        ordered = sorted(group, key=lambda r: (_utc(r["captured_at"], "captured_at"), r["match_id"]))
        for duplicate in ordered[1:]:
            if duplicate.get("status") == "settled":
                raise ValueError("Previously settled duplicate provider event requires review")
            if duplicate.get("status") == "pending":
                duplicate.update(status="excluded", excluded_reason="duplicate_provider_event_snapshot",
                                 primary_match_id=ordered[0]["match_id"])
    return result


def _paired_diagnostics(rows, *, minimum_segment=30):
    """Point-in-time, outcome-blind cohort coverage and descriptive winner scores.

    Never infer missing surface from tournament identity and never fit or select
    parameters from this cohort. Only rows with a verified settled outcome
    contribute to model accuracy and probability scoring.
    """
    active = [r for r in rows if r.get("status") != "excluded"]
    known_surfaces = {"hard", "clay", "grass", "carpet"}

    def surface(r):
        value = str(r.get("surface") or "").strip().lower()
        return value if value in known_surfaces else "unknown"

    settled = [r for r in active if r.get("status") == "settled"]

    def scored(group):
        n = len(group)
        if not n:
            return {"n": 0, "status": "NO_VERIFIED_OUTCOMES",
                    "champion": None, "candidate": None,
                    "champion_only_correct": 0, "candidate_only_correct": 0}
        champion_hits = candidate_hits = champion_only = candidate_only = 0
        champ_brier = cand_brier = champ_loss = cand_loss = 0.
        for r in group:
            truth = int(r["target_player1_win"])
            p = float(r["production_player1_probability"])
            q = float(r["challenger_player1_probability"])
            pc, qc = (p >= 0.5) == bool(truth), (q >= 0.5) == bool(truth)
            champion_hits += int(pc)
            candidate_hits += int(qc)
            champion_only += int(pc and not qc)
            candidate_only += int(qc and not pc)
            champ_brier += (p - truth) ** 2
            cand_brier += (q - truth) ** 2
            champ_loss -= math.log(p if truth else 1 - p)
            cand_loss -= math.log(q if truth else 1 - q)
        return {
            "n": n,
            "status": "DESCRIPTIVE_ONLY" if n < minimum_segment else "OBSERVED_NOT_CAUSAL",
            "champion": {
                "correct": champion_hits, "accuracy": round(champion_hits/n, 8),
                "brier_score": round(champ_brier/n, 8),
                "log_loss": round(champ_loss/n, 8),
            },
            "candidate": {
                "correct": candidate_hits, "accuracy": round(candidate_hits/n, 8),
                "brier_score": round(cand_brier/n, 8),
                "log_loss": round(cand_loss/n, 8),
            },
            "champion_only_correct": champion_only,
            "candidate_only_correct": candidate_only,
        }

    cover = {
        "total_excluding_repeated_snapshots": len(active),
        "by_tour": {tour: sum(str(r.get("tour")).upper() == tour for r in active)
                    for tour in ("ATP", "WTA")},
        "by_surface": {name: sum(surface(r) == name for r in active)
                       for name in ("hard", "clay", "grass", "carpet", "unknown")},
        "known_surface_rate": round(
            sum(surface(r) != "unknown" for r in active) / len(active), 8
        ) if active else None,
        "unknown_surface_settled": sum(surface(r) == "unknown" for r in settled),
        "unknown_surface_pending": sum(
            surface(r) == "unknown" for r in active if r.get("status") == "pending"),
        "no_surface_inference_or_backfill": True,
    }
    total = scored(settled)
    reasons = []
    if len(settled) < 200:
        reasons.append("fewer_than_200_verified_independent_settlements")
    if any(sum(str(r.get("tour")).upper() == tour for r in settled) < 50
           for tour in ("ATP", "WTA")):
        reasons.append("tour_split_insufficient")
    if active and cover["known_surface_rate"] < .8:
        reasons.append("prematch_surface_coverage_below_80_percent")
    if (total["champion"] and total["candidate"] and
            total["candidate"]["correct"] < total["champion"]["correct"]):
        reasons.append("candidate_accuracy_below_champion")
    return {
        "status": "PROSPECTIVE_DIAGNOSTIC_NOT_MODEL_SELECTION",
        "overall": total,
        "tour": {
            tour: scored([r for r in settled if str(r.get("tour")).upper() == tour])
            for tour in ("ATP", "WTA")
        },
        "surface": {
            name: scored([r for r in settled if surface(r) == name])
            for name in ("hard", "clay", "grass", "carpet", "unknown")
        },
        "coverage": cover,
        "review_blockers": reasons,
        "minimum_segment_settled": minimum_segment,
        "automatic_promotion": False,
        "retraining_or_recalibration_performed": False,
        "next_model_requires_independent_chronological_holdout": True,
    }


def research_frozen_721(payload, *, production_version, minimum_fit=200,
                        minimum_eval=100, minimum_tour_fit=100):
    """Diagnostic only: no production decision, writes, or provider requests."""
    rows, counts = validate_frozen_evidence(payload, production_version=production_version)
    rows = exclude_repeated_events(rows)
    _, counts = validate_frozen_evidence({**payload, "rows": rows}, production_version=production_version)
    result = research_comparison(
        rows, production_version, FROZEN_721_VERSION,
        minimum_fit=minimum_fit, minimum_eval=minimum_eval,
        minimum_tour_fit=minimum_tour_fit,
    )
    result["prospective_diagnostics"] = _paired_diagnostics(rows)
    result.update({
        "candidate_tag": FROZEN_721_TAG,
        "candidate_version": FROZEN_721_VERSION,
        "candidate_model_sha256": FROZEN_721_MODEL_SHA256,
        "cohort_counts": counts,
        "source": "independent_private_frozen_721_shadow_only",
        "provider_requests": 0,
        "automatic_promotion": False,
        "not_a_production_decision": True,
        "scope": "READ_ONLY_FROZEN_721_RESEARCH",
    })
    return result
