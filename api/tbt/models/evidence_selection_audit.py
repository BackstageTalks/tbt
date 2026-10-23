"""Read-only, outcome-blind audit of a FIXED pre-issued 7.2.1 pick cohort.

This never constructs historical picks, chooses thresholds, fetches odds, fits
models, imports CDB, or promotes a model. Upstream must freeze and independently
verify issued forecasts and their per-player PIT DIL snapshots. All issued rows,
including pending and void, participate in selection BEFORE scoring results.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from datetime import datetime, timezone
import math
from typing import Iterable, Mapping

from .evidence_lab import reliability_gate


_MIN_PRESTART_SECONDS = 15 * 60


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware original timestamps required")
    return value.astimezone(timezone.utc)


def _sha(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def issued_cohort_digest(rows: Iterable[Mapping]) -> str:
    """Canonical fingerprint of exactly the original pre-outcome opportunity set.

    Does NOT include settlement/outcome fields: those can arrive later without
    retroactively changing which tips existed or passed the evidence filter.
    The expected fingerprint must be pinned independently by the caller.
    """
    preissued = []
    fields = (
        "match_id", "tour", "competition_level", "evidence_provenance_verified",
        "left", "right", "model_probabilities", "candidate_probability_left",
        "selected_side", "candidate_model_sha256",
    )
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Invalid issued snapshot")
        item = {name: row.get(name) for name in fields}
        for name in ("issued_at", "scheduled_at", "evidence_as_of"):
            item[name] = _utc(row.get(name)).isoformat()
        preissued.append(item)
    preissued.sort(key=lambda x: str(x["match_id"]))
    try:
        serialized = json.dumps(preissued, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("Noncanonical frozen cohort evidence") from error
    return sha256(serialized.encode("utf-8")).hexdigest()


def _wilson(wins: int, total: int) -> list[float] | None:
    if not total:
        return None
    z = 1.959963984540054
    p = wins / total
    d = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / d
    radius = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total) / d
    return [round(max(0.0, center - radius), 6),
            round(min(1.0, center + radius), 6)]


def _summarize(rows: list[dict]) -> dict:
    settled = [r for r in rows if r["status"] == "settled"]
    n = len(settled)
    wins = sum(r["correct"] for r in settled)
    return {
        "issued": len(rows), "settled": n, "pending_or_void": len(rows) - n,
        "wins": wins, "losses": n - wins,
        "hit_rate": round(wins / n, 6) if n else None,
        "hit_rate_wilson_95": _wilson(wins, n),
        "mean_issued_probability": round(sum(r["pick_probability"] for r in settled) / n, 6)
        if n else None,
        "brier": round(sum((r["pick_probability"] - float(r["correct"])) ** 2
                           for r in settled) / n, 6) if n else None,
    }


def audit_preissued_reliability(
    rows: Iterable[Mapping], *,
    fixed_model_sha256: str,
    frozen_cohort_sha256: str,
    windows: Iterable[tuple[str, datetime, datetime]],
) -> dict:
    """Score a predeclared abstention gate, never retrospectively optimize it.

    Required row fields: match_id, tour (ATP/WTA), competition_level
    (main/challenger/itf), scheduled_at, issued_at, evidence_as_of,
    evidence_provenance_verified, left, right, model_probabilities,
    candidate_probability_left, selected_side (left/right), status
    (settled/pending/void), target_left_won (bool iff settled), settled_at
    (iff settled), candidate_model_sha256. Inputs must cover ALL pre-issued
    cohort opportunities, not merely surviving or settled tips. The cohort
    fingerprint is calculated on the pre-outcome fields, checked against an
    independently pinned digest, and never derived from settlement status.
    A hash alone is not provenance evidence.
    """
    if not _sha(fixed_model_sha256) or not _sha(frozen_cohort_sha256):
        raise ValueError("Pinned lowercase SHA256 model and source cohort required")
    # A frozen issued-set digest is independently compared before any selection.
    # A caller cannot silently add/remove a losing or pending opportunity.
    rows = list(rows)
    if issued_cohort_digest(rows) != frozen_cohort_sha256:
        raise ValueError("Frozen issued cohort SHA256 read-back mismatch")
    intervals = []
    for label, start, end in windows:
        a, b = _utc(start), _utc(end)
        if (not isinstance(label, str) or not label.strip() or a >= b
                or any(label == item[0] for item in intervals)):
            raise ValueError("Unique nonempty, forward-only predeclared windows required")
        intervals.append((label, a, b))
    intervals.sort(key=lambda v: v[1])
    if not intervals or any(x[2] > y[1] for x, y in zip(intervals, intervals[1:])):
        raise ValueError("Empty or overlapping holdout windows")

    selected = {label: [] for label, _, _ in intervals}
    seen = set()
    for item in rows:
        if not isinstance(item, Mapping):
            raise ValueError("Invalid immutable cohort row")
        if item.get("candidate_model_sha256") != fixed_model_sha256:
            raise ValueError("Issued forecast model digest differs from pinned candidate")
        mid = item.get("match_id")
        if not isinstance(mid, str) or not mid or mid in seen:
            raise ValueError("Missing or duplicate canonical match identity")
        seen.add(mid)
        tour = str(item.get("tour") or "").lower()
        level = str(item.get("competition_level") or "").lower()
        if tour not in ("atp", "wta") or level not in ("main", "challenger", "itf"):
            raise ValueError("Explicit ATP/WTA and competition level required")
        scheduled = _utc(item.get("scheduled_at"))
        issued = _utc(item.get("issued_at"))
        as_of = _utc(item.get("evidence_as_of"))
        if ((scheduled - issued).total_seconds() < _MIN_PRESTART_SECONDS
                or as_of != issued or item.get("evidence_provenance_verified") is not True):
            raise ValueError("Unverified or late PIT forecast/feature evidence")
        labels = [label for label, a, b in intervals if a <= issued < b]
        if len(labels) != 1:
            raise ValueError("Every issued row must belong to exactly one frozen window")
        p = item.get("candidate_probability_left")
        if (type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1):
            raise ValueError("Missing or invalid pinned candidate probability")
        side = item.get("selected_side")
        if side not in ("left", "right"):
            raise ValueError("Pre-issued winner side required")
        status = item.get("status")
        target = item.get("target_left_won")
        if status not in ("pending", "settled", "void"):
            raise ValueError("Explicit pending/settled/void required")
        if status == "settled":
            if type(target) is not bool or _utc(item.get("settled_at")) < scheduled:
                raise ValueError("Invalid settled outcome or settlement chronology")
        elif target is not None or item.get("settled_at") is not None:
            raise ValueError("Future/pending/void results must not be scored")

        left, right = item.get("left"), item.get("right")
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            raise ValueError("Verified left/right evidence snapshots required")
        if left.get("tour") != tour or right.get("tour") != tour:
            raise ValueError("PIT evidence tour mismatch")
        estimates = item.get("model_probabilities")
        if not isinstance(estimates, Mapping) or fixed_model_sha256 not in estimates:
            raise ValueError("Pinned candidate probability missing from model comparison")
        candidate = estimates[fixed_model_sha256]
        if (not isinstance(candidate, Mapping)
                or candidate.get("left_player_id") != left.get("canonical_player_id")
                or type(candidate.get("probability")) not in (int, float)
                or not math.isclose(candidate["probability"], p, abs_tol=1e-12, rel_tol=0)):
            raise ValueError("Issued candidate prediction mismatches frozen model comparison")
        # A comparison made after issuance is future information even when the
        # underlying historical DIL row was itself available in the past.
        families = set()
        for name, estimate in estimates.items():
            if not isinstance(estimate, Mapping):
                raise ValueError("Malformed independent estimator evidence")
            asof = _utc(estimate.get("captured_at"))
            if asof > issued or (scheduled - asof).total_seconds() < _MIN_PRESTART_SECONDS:
                raise ValueError("Late or in-play estimator prediction")
            family = estimate.get("estimator_family")
            if not isinstance(family, str) or not family.strip():
                raise ValueError("Verified estimator family required")
            families.add(family.strip().lower())
        gate = (reliability_gate(left, right, estimates) if len(families) >= 2
                else {"eligible": False, "reasons": ["missing_or_invalid_model_disagreement"]})
        confidence = float(p if side == "left" else 1 - p)
        selected[labels[0]].append({
            "match_id": mid, "tour": tour, "level": level,
            "confidence_band": "80_plus" if confidence >= .80 else "below_80",
            "pick_probability": confidence, "status": status,
            "correct": (target if side == "left" else not target)
            if status == "settled" else None,
            "eligible": gate["eligible"], "reasons": gate["reasons"],
        })

    result = {
        "status": "DESCRIPTIVE_FROZEN_PREISSUED_FILTER_AUDIT_NOT_MODEL_IMPROVEMENT",
        "model_sha256": fixed_model_sha256, "cohort_sha256": frozen_cohort_sha256,
        "windows": {}, "provider_requests": 0, "cdb_mutations": 0,
        "model_fitted": False, "production_mutated": False,
        "policy": "Thresholds fixed in evidence_lab; selection on complete issued cohort before settlement; no odds/ROI or training.",
    }
    for label, _, _ in intervals:
        cohort = selected[label]
        retained = [r for r in cohort if r["eligible"]]
        withheld = [r for r in cohort if not r["eligible"]]
        def segment(rows):
            return {
                "all_issued": _summarize(rows),
                "retained": _summarize([r for r in rows if r["eligible"]]),
                "withheld": _summarize([r for r in rows if not r["eligible"]]),
                "retention_rate": round(sum(r["eligible"] for r in rows) / len(rows), 6)
                if rows else None,
            }
        result["windows"][label] = {
            **segment(cohort),
            "gate_reasons": dict(Counter(reason for r in withheld for reason in r["reasons"])),
            "by_tour": {tour: segment([r for r in cohort if r["tour"] == tour])
                        for tour in ("atp", "wta")},
            "by_competition": {level: segment([r for r in cohort if r["level"] == level])
                               for level in ("main", "challenger", "itf")},
            "by_confidence": {band: segment([r for r in cohort if r["confidence_band"] == band])
                              for band in ("80_plus", "below_80")},
            "minimum_settled_for_claim": 100,
            "statistical_improvement_verified": False,
        }
    return result
