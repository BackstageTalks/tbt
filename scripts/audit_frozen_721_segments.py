"""Offline ATP/WTA, surface and confidence error audit of frozen v7.2.1.

Reads independently verified private original pre-match pairs. A descriptive
diagnostic, NEVER a model fit, accuracy-optimized selector, or promotion gate.
One case = one first issued provider event, and both model probabilities are
always evaluated on that exact same outcome. No EV, odds, ROI, or value logic.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from frozen_721_shadow_capture import LEDGER_ASSET, SHADOW_TAG
from release_store import ReleaseStore, gh
from tbt.models.metrics import evaluate_probabilities, wilson_interval
from tbt.services.frozen_721_research import (
    FROZEN_721_TAG,
    FROZEN_721_VERSION,
    FROZEN_721_MODEL_SHA256,
    validate_frozen_evidence,
    exclude_repeated_events,
)

DATA_REPO = "BackstageTalks/tbt-data"
SURFACES = ("hard", "indoor_hard", "clay", "grass", "carpet", "unknown")
MIN_DESCRIPTIVE_COHORT = 100


def _surface(value):
    surface = str(value or "").strip().lower().replace("-", "_")
    # Indoor is never inferred from tournament name; use only persisted facts.
    if surface in ("indoor", "hard_indoor"):
        return "indoor_hard"
    return surface if surface in SURFACES else "unknown"


def _confidence_bucket(candidate_probability):
    # Fixed before observing results; these are NOT model-selection thresholds.
    confidence = max(candidate_probability, 1 - candidate_probability)
    if confidence < .60:
        return "50-59%"
    if confidence < .70:
        return "60-69%"
    if confidence < .80:
        return "70-79%"
    if confidence < .90:
        return "80-89%"
    return "90-100%"


def _model_summary(y, probabilities):
    n = len(y)
    if not n:
        return {
            "n": 0, "correct": 0, "accuracy": None, "accuracy_ci95_wilson": None,
            "brier_score": None, "log_loss": None, "ece_10": None,
        }
    metrics = evaluate_probabilities(y, probabilities)
    correct = sum((p >= .5) == bool(truth) for p, truth in zip(probabilities, y))
    return {
        "n": n,
        "correct": correct,
        "accuracy": metrics["accuracy"],
        "accuracy_ci95_wilson": wilson_interval(correct, n),
        "brier_score": metrics["brier_score"],
        "log_loss": metrics["log_loss"],
        "ece_10": metrics["ece_10"],
    }


def _paired_group(rows):
    # Every score is paired for EXACT same immutable match IDs and outcomes.
    truths = [int(row["target_player1_win"]) for row in rows]
    prod = [float(row["production_player1_probability"]) for row in rows]
    challenger = [float(row["challenger_player1_probability"]) for row in rows]
    prod_summary = _model_summary(truths, prod)
    candidate_summary = _model_summary(truths, challenger)

    candidate_only = champion_only = both_correct = both_wrong = 0
    for y, p, c in zip(truths, prod, challenger):
        champion_hit = ((p >= .5) == bool(y))
        candidate_hit = ((c >= .5) == bool(y))
        if champion_hit and candidate_hit:
            both_correct += 1
        elif champion_hit:
            champion_only += 1
        elif candidate_hit:
            candidate_only += 1
        else:
            both_wrong += 1
    delta = {
        name: (
            round(candidate_summary[name] - prod_summary[name], 9)
            if rows else None
        )
        for name in ("accuracy", "brier_score", "log_loss", "ece_10")
    }
    return {
        "n": len(rows),
        "sample_size_flag": (
            "DESCRIPTIVE_ONLY_SMALL_N" if len(rows) < MIN_DESCRIPTIVE_COHORT
            else "DESCRIPTIVE_ONLY_NOT_VALIDATION"
        ),
        "champion": prod_summary, "frozen_721": candidate_summary,
        "candidate_minus_champion": delta,
        "paired_outcomes": {
            "both_correct": both_correct,
            "champion_only_correct": champion_only,
            "frozen_721_only_correct": candidate_only,
            "both_wrong": both_wrong,
            "discordant": champion_only + candidate_only,
        },
    }


def segment_diagnostics(payload, *, production_version):
    """Return descriptive scored partitions without changing immutable ledger."""
    rows, before = validate_frozen_evidence(
        payload, production_version=production_version
    )
    deduplicated = exclude_repeated_events(rows)
    _, after = validate_frozen_evidence(
        {**payload, "rows": deduplicated}, production_version=production_version
    )
    settled = [r for r in deduplicated if r.get("status") == "settled"]
    by_tour = defaultdict(list)
    by_surface = defaultdict(list)
    by_tour_surface = defaultdict(list)
    by_confidence = defaultdict(list)
    for row in settled:
        tour = str(row["tour"]).upper()
        surface = _surface(row.get("surface"))
        bucket = _confidence_bucket(float(row["challenger_player1_probability"]))
        by_tour[tour].append(row)
        by_surface[surface].append(row)
        by_tour_surface[f"{tour}/{surface}"].append(row)
        by_confidence[bucket].append(row)

    confidence_names = ("50-59%", "60-69%", "70-79%", "80-89%", "90-100%")
    report = {
        "schema": 1,
        "status": "DESCRIPTIVE_PREMATCH_SEGMENTS_ONLY",
        "source": "checksum_verified_private_frozen_721_shadow",
        "candidate_tag": FROZEN_721_TAG,
        "candidate_version": FROZEN_721_VERSION,
        "candidate_model_sha256": FROZEN_721_MODEL_SHA256,
        "production_version": production_version,
        "cohort_before_duplicate_exclusion": before,
        "cohort_after_duplicate_exclusion": after,
        "original_rows_untouched": True,
        "full_cohort": _paired_group(settled),
        "by_tour": {
            tour: _paired_group(by_tour[tour]) for tour in ("ATP", "WTA")
        },
        "by_surface": {
            surface: _paired_group(by_surface[surface]) for surface in SURFACES
        },
        "by_tour_surface": {
            group: _paired_group(by_tour_surface[group])
            for group in sorted(by_tour_surface)
        },
        "by_candidate_confidence": {
            group: _paired_group(by_confidence[group]) for group in confidence_names
        },
        "limitations": {
            "small_cohort_threshold": MIN_DESCRIPTIVE_COHORT,
            "significance_or_promotion_inferred": False,
            "confidence_bins_fixed_a_priori": True,
            "all_compared_models_on_identical_fixtures": True,
            "tournament_level_not_in_immutable_shadow_schema": True,
            "feature_ablation_not_possible_from_probability_only_ledger": True,
            "ATP_WTA_corrections_not_fitted_on_these_evaluation_rows": True,
            "not_an_independent_backtest_of_the_445_oct20_history_matches": True,
            "not_a_calibrated_model_or_recommendation_to_switch_champion": True,
        },
        "provider_requests": 0,
        "production_mutated": False,
        "automatic_promotion": False,
    }

    if (sum(report["by_tour"][k]["n"] for k in report["by_tour"]) != len(settled)
            or sum(report["by_surface"][k]["n"] for k in report["by_surface"]) != len(settled)
            or sum(report["by_candidate_confidence"][k]["n"] for k in report["by_candidate_confidence"]) != len(settled)):
        raise RuntimeError("Paired segment audit lost or double-counted matches")
    # Do not let NaN silently enter the signed read-only artifact.
    json.dumps(report, allow_nan=False)
    return report


def audit(*, repository=DATA_REPO, directory=None):
    if repository != DATA_REPO:
        raise ValueError("Unexpected private data repository")
    base = Path(directory or ROOT / ".cache/tbt/frozen-721-segment-analysis")
    # First probe existing release. ReleaseStore is not allowed to create a
    # missing research tag as a side effect of a read-only status check.
    gh("api", f"repos/{repository}/releases/tags/{SHADOW_TAG}")
    store = ReleaseStore(repository, SHADOW_TAG, base / "frozen-ledger")
    store.download(
        extra_names=(LEDGER_ASSET,),
        required_names=(LEDGER_ASSET,),
        require_bundle_manifest=True,
    )
    payload = json.loads(
        (store.directory / LEDGER_ASSET).read_text(encoding="utf-8")
    )
    source = payload.get("source") or {}
    return segment_diagnostics(
        payload, production_version=source.get("production_version")
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-repository",
        default=os.getenv("TBT_DATA_REPOSITORY", DATA_REPO),
    )
    parser.add_argument(
        "--output",
        default=".cache/tbt/frozen-721-prospective-segments.json",
    )
    args = parser.parse_args()
    report = audit(repository=args.data_repository)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, sort_keys=True, indent=2, allow_nan=False)+"\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "settled": report["full_cohort"]["n"],
        "ATP": report["by_tour"]["ATP"]["n"],
        "WTA": report["by_tour"]["WTA"]["n"],
        "champion_correct": report["full_cohort"]["champion"]["correct"],
        "candidate_correct": report["full_cohort"]["frozen_721"]["correct"],
        "duplicate_excluded": report["cohort_after_duplicate_exclusion"]["excluded"],
        "provider_requests": 0,
        "production_mutated": False,
        "automatic_promotion": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
