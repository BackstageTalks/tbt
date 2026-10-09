"""Validated admin-only model-calibration snapshot; never a promotion command.

Only the secret-authenticated GitHub worker can publish this read-only report.
The candidate/cohort is always keyed by the exact production/challenger pair;
a previous promotion decision remains historical, not a live go/no-go signal.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite


MODEL_CALIBRATION_BRANCH = "research/model-calibration"
MODEL_CALIBRATION_BRANCH_URL = (
    "https://github.com/BackstageTalks/tbt/tree/" + MODEL_CALIBRATION_BRANCH
)
SHADOW_TARGET_MATCHES = 1000
NEXT_UNSEEN_TARGET_MATCHES = 1000
SNAPSHOT_STALE_SECONDS = 8 * 3600


def _bounded_text(value: object, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


def _nonnegative(value: object, name: str) -> int:
    if type(value) is not int or value < 0 or value > 5_000_000:
        raise ValueError(f"Invalid calibration count: {name}")
    return value


def _metric_row(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ("accuracy", "log_loss", "brier_score", "ece_10", "roc_auc"):
        raw = value.get(key)
        if type(raw) in (int, float) and isfinite(raw):
            number = float(raw)
            if (key == "log_loss" and 0 <= number <= 100) or (
                key != "log_loss" and 0 <= number <= 1
            ):
                result[key] = number
    return result


def _timestamp(value: object) -> str:
    text = _bounded_text(value, 64)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid calibration report timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("Calibration timestamp needs timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_model_calibration_snapshot(raw: object) -> dict:
    if not isinstance(raw, dict) or raw.get("schema") != 1:
        raise ValueError("Invalid model calibration snapshot schema")
    generated_at = _timestamp(raw.get("source_generated_at"))
    if not generated_at:
        raise ValueError("Missing calibration source time")
    production = _bounded_text(raw.get("production_version"))
    candidate = _bounded_text(raw.get("candidate_version"))
    if not production:
        raise ValueError("Production version is required")
    shadow = raw.get("shadow")
    if not isinstance(shadow, dict):
        raise ValueError("Shadow report is required")
    shadow_prod = _bounded_text(shadow.get("production_model_version"))
    shadow_candidate = _bounded_text(shadow.get("challenger_model_version"))
    if shadow_prod != production or shadow_candidate != candidate:
        raise ValueError("Shadow model versions do not match source release")
    cohort = shadow.get("cohort")
    if not isinstance(cohort, dict):
        raise ValueError("Shadow cohort is required")
    captured = _nonnegative(cohort.get("captured"), "captured")
    settled = _nonnegative(cohort.get("settled"), "settled")
    pending = _nonnegative(cohort.get("pending"), "pending")
    days = _nonnegative(cohort.get("settled_utc_days"), "settled_utc_days")
    if settled > captured or pending > captured or settled + pending > captured:
        raise ValueError("Impossible shadow cohort counters")
    gate = shadow.get("gate") if isinstance(shadow.get("gate"), dict) else {}
    readiness = raw.get("readiness") if isinstance(raw.get("readiness"), dict) else {}
    # The readiness audit has a different timeline from the shadow cohort.
    # Reject a stale champion's count rather than showing a false fresh sample.
    readiness_production = _bounded_text(readiness.get("production_version"))
    same_champion = bool(readiness_production == production)
    unseen = (
        _nonnegative(readiness.get("eligible_unseen_rows"), "eligible_unseen_rows")
        if same_champion else None
    )
    eligible_days = (
        _nonnegative(readiness.get("eligible_unseen_days"), "eligible_unseen_days")
        if same_champion else None
    )
    min_gate = (
        _nonnegative(readiness.get("minimum_gate_rows"), "minimum_gate_rows")
        if same_champion else 200
    )
    target = (
        _nonnegative(readiness.get("recommended_target_rows"), "recommended_target_rows")
        if same_champion else NEXT_UNSEEN_TARGET_MATCHES
    )
    last = raw.get("last_decision") if isinstance(raw.get("last_decision"), dict) else {}
    decision_pair = bool(
        _bounded_text(last.get("candidate_version")) == candidate
        and _bounded_text(last.get("production_version")) == production
    )
    return {
        "schema": 1,
        "source_generated_at": generated_at,
        "shadow_generated_at": _timestamp(shadow.get("generated_at_utc")) if shadow.get("generated_at_utc") else None,
        "production_version": production,
        "candidate_version": candidate or None,
        "candidate_active": bool(candidate and candidate != production),
        "research_branch": MODEL_CALIBRATION_BRANCH,
        "research_branch_url": MODEL_CALIBRATION_BRANCH_URL,
        "shadow": {
            "captured": captured, "settled": settled, "pending": pending,
            "settled_utc_days": days,
            "minimum_for_review": _nonnegative(
                cohort.get("minimum_for_review"), "minimum_for_review"
            ),
            "target_for_tracking": SHADOW_TARGET_MATCHES,
            "remaining_to_review": max(
                0, _nonnegative(cohort.get("minimum_for_review"), "minimum_for_review") - settled
            ),
            "remaining_to_target": max(0, SHADOW_TARGET_MATCHES - settled),
            "production": _metric_row(shadow.get("production")),
            "candidate": _metric_row(shadow.get("challenger")),
            "gate": {
                key: bool(gate.get(key))
                for key in (
                    "minimum_matches_met", "minimum_days_met",
                    "accuracy_not_worse", "log_loss_better",
                    "brier_better", "ece_not_worse", "ready_for_promotion_review"
                )
            },
        },
        "unseen": {
            "available": same_champion,
            "eligible_rows": unseen,
            "eligible_days": eligible_days,
            "minimum_for_review": min_gate,
            "target_for_retrain": target,
            "remaining_to_review": max(0, min_gate - unseen) if unseen is not None else None,
            "remaining_to_target": max(0, target - unseen) if unseen is not None else None,
            "readiness_generated_at": _timestamp(readiness.get("generated_at_utc"))
                if same_champion and readiness.get("generated_at_utc") else None,
            "reason": None if same_champion else "readiness_champion_version_mismatch",
        },
        "last_decision": {
            "status": _bounded_text(last.get("status"), 40) or "none",
            "candidate_version": _bounded_text(last.get("candidate_version")) or None,
            "production_version": _bounded_text(last.get("production_version")) or None,
            "same_pair": decision_pair,
            "decided_at": _timestamp(last.get("decided_at")) if last.get("decided_at") else None,
            "reason_codes": [
                _bounded_text(reason, 100)
                for reason in (last.get("reason_codes") or [])[:12]
                if isinstance(reason, str)
            ],
        },
        "automatic_promotion": False,
        "source": "private_github_releases_and_readiness_audit",
    }


def with_freshness(record: object, *, now: datetime | None = None) -> dict:
    if not isinstance(record, dict):
        raise ValueError("Calibration status is unavailable")
    now = now or datetime.now(timezone.utc)
    updated_at = _timestamp(record.get("updated_at"))
    if not updated_at:
        raise ValueError("Calibration update time is unavailable")
    age = max(0, int((now - datetime.fromisoformat(updated_at)).total_seconds()))
    return {
        **record, "age_seconds": age,
        "stale": age > SNAPSHOT_STALE_SECONDS,
        "promotion_permitted": False,
    }
