"""Validated admin-only model-calibration snapshot; never a promotion command.

Only the secret-authenticated GitHub worker can publish this read-only report.
The candidate/cohort is always keyed by the exact production/challenger pair;
a previous promotion decision remains historical, not a live go/no-go signal.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
import hashlib
import json


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



def _paired_interval(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    n = _nonnegative(value.get("n"), "paired_n")
    result = {"n": n}
    for key in ("delta", "lower", "upper"):
        raw = value.get(key)
        if raw is None:
            result[key] = None
        elif type(raw) in (int, float) and isfinite(raw) and -100 <= float(raw) <= 100:
            result[key] = float(raw)
        else:
            raise ValueError("Invalid paired shadow confidence interval")
    if result["lower"] is not None and result["upper"] is not None and (
        result["lower"] > result["upper"] or
        result["delta"] is None or
        not result["lower"] <= result["delta"] <= result["upper"]
    ):
        raise ValueError("Inconsistent paired confidence bounds")
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


def _offline_candidate(raw: object, production_version: str) -> dict | None:
    """Validate separate untouched-holdout evidence; never label it as shadow."""
    if not isinstance(raw, dict):
        return None
    if (raw.get("schema") != 1 or raw.get("status") != "EVALUATED_NOT_DEPLOYED"
            or raw.get("evaluation_type") != "untouched_offline_holdout"
            or raw.get("promotion_requested") is not False
            or raw.get("model_promoted") is not False
            or raw.get("backup_readback_verified") is not True
            or raw.get("champion_restore_verified") is not True
            or raw.get("candidate_remote_readback_verified") is not True):
        raise ValueError("Unverified new offline model candidate evidence")
    champion = _bounded_text(raw.get("champion_version"))
    candidate = _bounded_text(raw.get("candidate_version"))
    if champion != production_version:
        # Keep the historic comparison separate; do not show it as current.
        return None
    if not candidate or candidate == champion:
        raise ValueError("Offline candidate is not different from serving champion")
    tag = _bounded_text(raw.get("candidate_release_tag"))
    if not tag.startswith("blinq-candidate-frozen-"):
        raise ValueError("Candidate release must be separately frozen")
    if not isinstance(raw.get("candidate_sha256"), str) or len(raw["candidate_sha256"]) != 64:
        raise ValueError("Candidate binary SHA missing")
    comparison = raw.get("comparison")
    if not isinstance(comparison, dict):
        raise ValueError("Offline comparison missing")
    n = _nonnegative(comparison.get("sample_size"), "offline_sample_size")
    if n < 200:
        raise ValueError("Offline model holdout too small")
    def metrics(name):
        block = comparison.get(name)
        if not isinstance(block, dict) or type(block.get("n")) is not int or block["n"] != n:
            raise ValueError("Offline champion/candidate holdout sample mismatch")
        row = _metric_row(block)
        if any(key not in row for key in ("accuracy", "log_loss", "brier_score", "ece_10")):
            raise ValueError("Incomplete offline holdout metrics")
        return row
    return {
        "status": "evaluated_not_deployed",
        "evaluation_type": "untouched_offline_holdout",
        "candidate_version": candidate,
        "production_version": champion,
        "candidate_release_tag": tag,
        "candidate_sha256": raw["candidate_sha256"],
        "backup_tag": _bounded_text(raw.get("backup_tag")),
        "run_id": _bounded_text(raw.get("run_id"), 30),
        "generated_at_utc": _timestamp(raw.get("generated_at_utc")),
        "n": n,
        "champion": metrics("champion"),
        "candidate": metrics("candidate"),
        "promotion_requested": False,
        "model_promoted": False,
    }


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
    pair_state = raw.get("shadow_pair_state", "current")
    if pair_state not in ("current", "awaiting_new_pair"):
        raise ValueError("Invalid shadow-pair state")
    historic = raw.get("historical_shadow_pair")
    if pair_state == "awaiting_new_pair":
        if (candidate or any((captured, settled, pending, days))
                or not isinstance(historic, dict)
                or not _bounded_text(historic.get("production_version"))
                or _bounded_text(historic.get("production_version")) == production):
            raise ValueError("Promoted champion cannot inherit stale shadow cohort")
        if shadow.get("production") or shadow.get("challenger"):
            raise ValueError("Promoted champion cannot inherit old shadow metrics")
    else:
        historic = None
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
        "shadow_pair_state": pair_state,
        "historical_shadow_pair": ({
            "production_version": _bounded_text(historic.get("production_version")),
            "candidate_version": _bounded_text(historic.get("candidate_version")),
        } if historic is not None else None),
        "research_branch": MODEL_CALIBRATION_BRANCH,
        "research_branch_url": MODEL_CALIBRATION_BRANCH_URL,
        "shadow": {
            "captured": captured, "settled": settled, "pending": pending,
            "settled_utc_days": days,
            "minimum_days_for_review": _nonnegative(cohort.get("minimum_days_for_review", 3), "minimum_days_for_review"),
            "minimum_for_review": _nonnegative(
                cohort.get("minimum_for_review"), "minimum_for_review"
            ),
            "target_for_tracking": SHADOW_TARGET_MATCHES,
            "remaining_to_review": max(
                0, _nonnegative(cohort.get("minimum_for_review"), "minimum_for_review") - settled
            ),
            # Tracking target counts captured immutable pre-match pairs; review
            # minimum above counts only genuinely settled results.
            "remaining_to_target": max(0, SHADOW_TARGET_MATCHES - captured),
            "paired_uncertainty": {
                key: _paired_interval(shadow.get("paired_uncertainty", {}).get(key))
                for key in ("accuracy", "log_loss", "brier_score")
            } if isinstance(shadow.get("paired_uncertainty"), dict) else {},
            "tour_diagnostics": {
                tour: {
                    "n": _nonnegative(shadow["tour_diagnostics"][tour].get("n"), tour+"_n"),
                    "paired_log_loss": _paired_interval(shadow["tour_diagnostics"][tour].get("paired_log_loss")),
                }
                for tour in ("ATP", "WTA")
                if isinstance(shadow.get("tour_diagnostics"), dict)
                and isinstance(shadow["tour_diagnostics"].get(tour), dict)
            },
            "production": _metric_row(shadow.get("production")),
            "candidate": _metric_row(shadow.get("challenger")),
            "gate": {
                key: bool(gate.get(key))
                for key in (
                    "minimum_matches_met", "minimum_days_met",
                    "accuracy_not_worse", "log_loss_better",
                    "brier_better", "ece_not_worse", "ready_for_promotion_review",
                    "accuracy_within_tolerance", "brier_within_tolerance"
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
        "offline_candidate": _offline_candidate(raw.get("offline_candidate"), production),
        "source": "private_github_releases_and_readiness_audit",
    }



def calibration_fingerprint(record: dict) -> str:
    """Stable digest of every accepted source datum, without wall-clock metadata."""
    data = {key: value for key, value in record.items()
            if key not in ("updated_at", "snapshot_sha256", "age_seconds",
                           "stale", "promotion_permitted", "health_warnings")}
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def assert_calibration_successor(previous: dict, incoming: dict) -> bool:
    """Return True for newer evidence, False for exact retry; reject regressions.

    Production changes are allowed only as a distinct (already independently
    digest-verified by the publisher) cohort. They never inherit old metrics.
    """
    old_time = _timestamp(previous.get("source_generated_at"))
    new_time = _timestamp(incoming.get("source_generated_at"))
    if not old_time or not new_time:
        raise ValueError("Calibration source timestamp missing")
    old_date = datetime.fromisoformat(old_time)
    new_date = datetime.fromisoformat(new_time)
    if new_date < old_date:
        raise ValueError("Stale calibration snapshot rejected")
    same_pair = (previous.get("production_version"), previous.get("candidate_version")) == (
        incoming.get("production_version"), incoming.get("candidate_version"))
    if new_date == old_date:
        if calibration_fingerprint(previous) == calibration_fingerprint(incoming):
            return False
        raise ValueError("Conflicting calibration snapshots share a timestamp")
    if same_pair:
        for key in ("captured", "settled", "settled_utc_days"):
            if incoming["shadow"][key] < previous["shadow"][key]:
                raise ValueError("Calibration shadow cohort regressed: " + key)
        # A later Azure publication must not accidentally replace a newly
        # generated evidence report with an older release or CDB audit.
        for key in ("shadow_generated_at",):
            old_stamp, new_stamp = previous.get(key), incoming.get(key)
            if old_stamp and (not new_stamp or _timestamp(new_stamp) < _timestamp(old_stamp)):
                raise ValueError("Calibration shadow evidence regressed")
        if previous.get("unseen", {}).get("available") and incoming.get("unseen", {}).get("available"):
            old_audit = previous["unseen"].get("readiness_generated_at")
            new_audit = incoming["unseen"].get("readiness_generated_at")
            if old_audit and (not new_audit or _timestamp(new_audit) < _timestamp(old_audit)):
                raise ValueError("Calibration readiness evidence regressed")
            old_rows = previous["unseen"].get("eligible_rows")
            new_rows = incoming["unseen"].get("eligible_rows")
            if old_rows is not None and (new_rows is None or new_rows < old_rows):
                raise ValueError("Calibration unseen-data sample regressed")
    return True


def calibration_health_warnings(record: dict, now: datetime) -> list[str]:
    warnings = []
    for key, label in (("shadow_generated_at", "shadow_report_stale"),
                       ("source_generated_at", "source_report_stale")):
        stamp = record.get(key)
        if not stamp or (now - datetime.fromisoformat(_timestamp(stamp))).total_seconds() > SNAPSHOT_STALE_SECONDS:
            warnings.append(label)
    audit = record.get("unseen", {}).get("readiness_generated_at")
    if record.get("unseen", {}).get("available") and (
        not audit or (now - datetime.fromisoformat(_timestamp(audit))).total_seconds() > SNAPSHOT_STALE_SECONDS
    ):
        warnings.append("readiness_audit_stale")
    if record.get("shadow", {}).get("pending", 0) > 0 and "shadow_report_stale" in warnings:
        warnings.append("pending_shadow_requires_review")
    return warnings


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
        "health_warnings": calibration_health_warnings(record, now),
    }
