"""Read-only provenance overlap audit: champion-unseen != frozen 7.2.1-unseen.

The 4544 completed Oct 9-20 matches reported by model_promotion_readiness
were never certified unseen for the newly frozen v7.2.1. Its selection holdout
and serving fit use a later cutoff than the incumbent champion. This script
reports only defensible cohort counts, NEVER calculates candidate win metrics
or reuses retrospectively predicted matches as prospective evidence.

No paid API requests, writes to tbt-data, retraining, or promotion.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, date, timezone
import hashlib
import json
import os
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from model_promotion_readiness import _load_governance, _load_history, build_readiness
from release_store import ReleaseStore
from tbt.models.artifact import load_model
from tbt.services.data_quality import audit_history
from tbt.services.frozen_721_research import (
    FROZEN_721_TAG, FROZEN_721_VERSION, FROZEN_721_MODEL_SHA256,
)

DATA_REPO = "BackstageTalks/tbt-data"


def strict_utc(value, field):
    if not isinstance(value, (datetime, str)) or not value:
        raise ValueError(f"Missing frozen candidate provenance: {field}")
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid frozen candidate provenance: {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"Naive frozen candidate provenance: {field}")
    return dt.astimezone(timezone.utc)


def candidate_provenance(candidate_model, report, production_version):
    """Strictly enforce consumed model fit, calibration AND evaluated holdout."""
    metadata = getattr(candidate_model, "metadata", None)
    if not isinstance(metadata, dict) or not isinstance(report, dict):
        raise ValueError("Missing candidate artifact / report provenance")
    if str(candidate_model.version) != FROZEN_721_VERSION:
        raise ValueError("Unexpected frozen candidate version")
    decision = report.get("promotion_decision")
    governance = report.get("evaluation_governance")
    if not isinstance(decision, dict) or not isinstance(governance, dict):
        raise ValueError("Missing frozen 7.2.1 evaluation governance")
    if (
        decision.get("candidate_version") != FROZEN_721_VERSION
        or decision.get("production_version") != production_version
        or decision.get("promotion_requested") is not False
        or not governance.get("holdout_fingerprint")
    ):
        raise ValueError("Frozen candidate / incumbent holdout provenance mismatch")
    period = decision.get("holdout_period")
    if not isinstance(period, dict):
        raise ValueError("Missing frozen candidate evaluated holdout period")

    required_dates = {
        "serving_fit_history_end": strict_utc(metadata.get("history_end"), "history_end"),
        "serving_evaluation_end": strict_utc(metadata.get("evaluation_end"), "evaluation_end"),
        "evaluated_holdout_end": strict_utc(period.get("end"), "holdout_period.end"),
        "evaluated_holdout_start": strict_utc(period.get("start"), "holdout_period.start"),
    }
    if required_dates["evaluated_holdout_start"] > required_dates["evaluated_holdout_end"]:
        raise ValueError("Frozen candidate holdout period is reversed")
    extra_fields = ("selection_history_end", "selection_evaluation_end")
    for name in extra_fields:
        if metadata.get(name) not in (None, ""):
            required_dates[name] = strict_utc(metadata[name], name)

    # A completed UTC calendar day is candidate-clean only if ALL data
    # consumption and evaluation happened before that UTC day.
    latest_used = max(
        when for label, when in required_dates.items()
        if label != "evaluated_holdout_start"
    )
    return {
        "frozen_candidate_version": FROZEN_721_VERSION,
        "production_version": production_version,
        "last_consumed_utc_day": latest_used.date().isoformat(),
        "last_consumed_timestamp_utc": latest_used.isoformat(),
        "selection_holdout_period_utc": {
            "start": required_dates["evaluated_holdout_start"].isoformat(),
            "end": required_dates["evaluated_holdout_end"].isoformat(),
        },
        "cutoff_sources_utc": {
            k: v.isoformat() for k, v in required_dates.items()
        },
        "selection_holdout_fingerprint_verified": True,
    }


def partition_champion_unseen(matches, champion_readiness, provenance, *, as_of):
    """Split only the ORIGINAL champion-ready cohort into overlap and new days.

    Identical quality, cutoff, full-UTC-day and match-identity policies to the
    existing readiness gate. Conservative calendar-day quarantine means no
    match on a day consumed by v7.2.1 can be called newly unseen.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Timezone-aware cohort audit time required")
    as_of = as_of.astimezone(timezone.utc)
    today = as_of.date()
    champion_day = date.fromisoformat(champion_readiness["eligibility_cutoff_day_utc"])
    candidate_day = date.fromisoformat(provenance["last_consumed_utc_day"])
    if candidate_day < champion_day:
        raise ValueError("Candidate unexpectedly precedes production decision cutoff")

    accepted, _ = audit_history(matches)
    eligible = []
    seen = set()
    for match in accepted:
        day = match.scheduled_at.astimezone(timezone.utc).date()
        if not champion_day < day < today:
            continue
        key = str(match.match_id)
        if key in seen:
            raise ValueError("Duplicate identity in canonically accepted unseen cohort")
        seen.add(key)
        eligible.append(match)
    if len(eligible) != champion_readiness["eligible_unseen_rows"]:
        raise RuntimeError("Frozen 7.2.1 overlap disagrees with incumbent readiness cohort")
    used, fresh = [], []
    for match in eligible:
        day = match.scheduled_at.astimezone(timezone.utc).date()
        (fresh if day > candidate_day else used).append(match)

    def description(sample):
        return {
            "rows": len(sample),
            "utc_days": len({x.scheduled_at.astimezone(timezone.utc).date() for x in sample}),
            "by_tour": dict(sorted(Counter(str(x.tour).lower() for x in sample).items())),
            "earliest": min((x.scheduled_at.isoformat() for x in sample), default=None),
            "latest": max((x.scheduled_at.isoformat() for x in sample), default=None),
        }

    return {
        "schema": 1,
        "status": "STRICT_CANDIDATE_COHORT_OVERLAP_AUDIT_NOT_MODEL_EVALUATION",
        "as_of_utc": as_of.isoformat(),
        "current_utc_day_excluded": today.isoformat(),
        "champion_cutoff_utc_day": champion_day.isoformat(),
        "candidate_consumed_cutoff_utc_day": candidate_day.isoformat(),
        "champion_unseen_reported": champion_readiness["eligible_unseen_rows"],
        "overlap_with_frozen_721_consumption_or_evaluation": description(used),
        "strictly_after_all_frozen_721_consumption": description(fresh),
        "row_count_verified": len(used) + len(fresh) == len(eligible),
        "candidate_fresh_rows_are_not_prospective_predictions": True,
        "can_fit_721_calibration_from_champion_unseen_rows": False,
        "can_use_overlap_for_exploratory_diagnostics": True,
        "production_promotion_approved": False,
        "top_odds_roi_proven": False,
        "provider_requests": 0,
        "production_mutated": False,
    }


def audit(repo=DATA_REPO, *, as_of=None):
    if repo != DATA_REPO:
        raise ValueError("Unexpected private data repository")
    now = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    model, promotion_history = _load_governance(repo)
    matches = _load_history(repo)
    champion = build_readiness(
        matches, production_model=model, promotion_history=promotion_history,
        as_of=now,
    )

    folder = ROOT / ".cache/tbt/frozen-721-unseen-overlap"
    store = ReleaseStore(repo, FROZEN_721_TAG, folder)
    store.download(
        extra_names=("model.joblib", "training_report.json"),
        required_names=("model.joblib", "training_report.json"),
        require_bundle_manifest=True,
    )
    if hashlib.sha256((folder / "model.joblib").read_bytes()).hexdigest() != FROZEN_721_MODEL_SHA256:
        raise ValueError("Frozen 7.2.1 candidate model bytes are not the pinned artifact")
    candidate = load_model(str(folder / "model.joblib"))
    report = json.loads((folder / "training_report.json").read_text(encoding="utf-8"))
    provenance = candidate_provenance(candidate, report, model.version)
    split = partition_champion_unseen(matches, champion, provenance, as_of=now)
    split["candidate"] = provenance
    split["candidate_sha256"] = FROZEN_721_MODEL_SHA256
    return split


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", DATA_REPO))
    parser.add_argument("--out", default=".cache/tbt/frozen-721-unseen-overlap.json")
    args = parser.parse_args()
    result = audit(repo=args.data_repository)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
