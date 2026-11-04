"""Reconstruct an exploratory quality-availability gate from audited annual folds.

No fitting, CDB reads/writes, provider calls, odds or EV optimization.
A weighted composition of pre-existing *out-of-year model predictions*
is still an in-sample choice of the GATING RULE: NOT promotion evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

METRICS = ("accuracy", "brier", "log_loss")
ARMS = ("with_quality", "without_quality")
GATE = {"True": "with_quality", "False": "without_quality"}
REVERSE_GATE = {"True": "without_quality", "False": "with_quality"}


def require_metric(value, key):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"non-numeric {key}") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"non-finite or negative {key}")
    if key == "accuracy" and number > 1:
        raise ValueError("accuracy outside unit interval")
    return number


def aggregate(grouped, choose):
    count = sum(row["with_quality"]["n"] for row in grouped.values())
    if not count:
        raise ValueError("no matched observations")
    return {"n": count, **{
        metric: sum(row[choose[group]]["n"] * row[choose[group]][metric]
                    for group, row in grouped.items()) / count
        for metric in METRICS
    }}


def evaluate(document, *, source_sha256):
    if (not isinstance(document, dict) or document.get("phase") != "complete"
            or document.get("purpose") != "retrospective_annual_ablation_not_promotion"
            or document.get("production_mutated") is not False
            or document.get("provider_requests") != 0):
        raise ValueError("source audit is not the expected complete read-only research report")
    grouped = document.get("by_quality_availability")
    if not isinstance(grouped, dict) or set(grouped) != {"True", "False"}:
        raise ValueError("pre-match availability groups missing or ambiguous")
    for key, row in grouped.items():
        if not isinstance(row, dict) or not all(arm in row for arm in ARMS):
            raise ValueError("missing matched quality arms")
        counts = []
        for arm in ARMS:
            sample = row[arm]
            n = sample.get("n")
            if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
                raise ValueError("invalid matched denominator")
            counts.append(n)
            for metric in METRICS:
                sample[metric] = require_metric(sample.get(metric), metric)
        if len(set(counts)) != 1:
            raise ValueError(f"non-identical event populations: {key}")
    overall = document.get("overall")
    if not isinstance(overall, dict):
        raise ValueError("overall independent readback absent")
    years = document.get("folds")
    if not isinstance(years, list) or {y.get("year") for y in years} != {2023, 2024, 2025, 2026}:
        raise ValueError("annual folds 2023-2026 missing")
    total = sum(row["with_quality"]["n"] for row in grouped.values())
    if sum(y.get("partitions", {}).get("test", {}).get("n", 0) for y in years) != total:
        raise ValueError("annual folds disagree with cohort")
    arms = {
        name: aggregate(grouped, {key: name for key in grouped})
        for name in ARMS
    }
    for name in ARMS:
        baseline = overall.get(name)
        if not isinstance(baseline, dict) or baseline.get("n") != total:
            raise ValueError("overall denominator mismatches grouped cohort")
        for metric in METRICS:
            if abs(arms[name][metric] - require_metric(baseline.get(metric), metric)) > 1e-10:
                raise ValueError(f"independent aggregate consistency failed for {name}/{metric}")
    gated = aggregate(grouped, GATE)
    reversed_gate = aggregate(grouped, REVERSE_GATE)
    return {
        "schema": "BLINQ_HISTORICAL_QUALITY_AVAILABILITY_GATE_V1",
        "status": "RECONSTRUCTED_EXPLORATORY_ONLY",
        "source_sha256": source_sha256,
        "source_fold_years": sorted(y["year"] for y in years),
        "source_training_rows": document.get("source_rows"),
        "model_feature_contract_reference": document.get("feature_contract_reference"),
        "selected_gate": "with_quality only when pre-match stats_known_both > 0; otherwise without_quality",
        "cohort": {
            "all_observations": total,
            "stats_known_both": grouped["True"]["with_quality"]["n"],
            "stats_not_known_both": grouped["False"]["with_quality"]["n"],
        },
        "arms": {**arms, "availability_gated": gated, "reversed_gate_negative_control": reversed_gate},
        "gated_delta_vs_always_quality": {
            metric: gated[metric] - arms["with_quality"][metric] for metric in METRICS
        },
        "gated_delta_vs_never_quality": {
            metric: gated[metric] - arms["without_quality"][metric] for metric in METRICS
        },
        "validation_gates": {
            "same_event_group_aggregate_readback": True,
            "pretrained_annual_folds": True,
            "gate_rule_outcome_selected_on_full_2023_2026_cohort": True,
            "year_specific_gated_holdout": "NOT_AVAILABLE_IN_AGGREGATE_SOURCE",
            "prospective_independent_confirmation": False,
            "actual_serving_feature_asof_readback": False,
            "production_release_ready": False,
        },
        "interpretation_limits": [
            "This is an exact weighted combination of audited, disjoint subgroup scores, NOT new per-event inference.",
            "The two original model arms used chronological year-ahead predictions; the GATE was chosen after seeing subgroup outcomes.",
            "No year-by-year conditional scores are stored, so this cannot establish stability by year or a true untouched holdout.",
            "Stats-known must be separately verified as point-in-time, as not all current CDB fields were available before match start.",
            "The composition improves neither the actual serving champion nor live selection until separately trained, frozen and validated.",
        ],
        "provider_requests": 0,
        "training_performed": False,
        "cdb_mutated": False,
        "production_mutated": False,
        "candidate_promoted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    result = evaluate(json.loads(raw), source_sha256=hashlib.sha256(raw).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "cohort": result["cohort"],
                      "arms": result["arms"], "promotion_ready": False}))


if __name__ == "__main__":
    main()
