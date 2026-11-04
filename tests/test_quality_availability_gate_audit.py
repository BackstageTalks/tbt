"""No provider/CDB calls: synthetic checks for immutable annual aggregation."""
import copy
import pytest
from research.quality_availability_gate_audit import evaluate, aggregate, GATE


def fixture():
    present = {
        "with_quality": {"n": 4, "accuracy": .75, "brier": .12, "log_loss": .40},
        "without_quality": {"n": 4, "accuracy": .50, "brier": .17, "log_loss": .55},
    }
    absent = {
        "with_quality": {"n": 4, "accuracy": .25, "brier": .25, "log_loss": .85},
        "without_quality": {"n": 4, "accuracy": .50, "brier": .20, "log_loss": .70},
    }
    groups = {"True": present, "False": absent}
    return {
        "purpose": "retrospective_annual_ablation_not_promotion",
        "phase": "complete",
        "production_mutated": False, "provider_requests": 0,
        "source_rows": 800,
        "feature_contract_reference": "frozen",
        "by_quality_availability": groups,
        "folds": [
            {"year": year, "partitions": {"test": {"n": 2}}}
            for year in (2023, 2024, 2025, 2026)
        ],
        "overall": {
            arm: aggregate(groups, {"True": arm, "False": arm})
            for arm in ("with_quality", "without_quality")
        },
    }


def test_gate_exact_weighted_disjoint_cohort():
    report = evaluate(fixture(), source_sha256="sha-only")
    arms = report["arms"]
    assert report["cohort"]["all_observations"] == 8
    assert report["cohort"]["stats_known_both"] == 4
    assert arms["availability_gated"]["accuracy"] == .625
    assert arms["availability_gated"]["log_loss"] == .55
    assert arms["availability_gated"]["brier"] == .16
    assert arms["reversed_gate_negative_control"]["accuracy"] == .375
    assert report["validation_gates"]["prospective_independent_confirmation"] is False
    assert report["candidate_promoted"] is False
    assert report["training_performed"] is False
    assert report["production_mutated"] is False


def test_identity_of_matched_populations_required():
    doc = fixture()
    doc["by_quality_availability"]["True"]["with_quality"]["n"] += 1
    with pytest.raises(ValueError, match="non-identical event"):
        evaluate(doc, source_sha256="sha")


def test_crosscheck_with_independent_overall_is_mandatory():
    doc = fixture()
    doc["overall"]["with_quality"]["brier"] += .01
    with pytest.raises(ValueError, match="independent aggregate"):
        evaluate(doc, source_sha256="sha")


def test_all_years_required_to_label_historical_range():
    doc = fixture()
    doc["folds"] = doc["folds"][:-1]
    with pytest.raises(ValueError, match="annual folds"):
        evaluate(doc, source_sha256="sha")


def test_source_readonly_credential_gate():
    doc = fixture()
    doc["production_mutated"] = True
    with pytest.raises(ValueError, match="expected complete read-only"):
        evaluate(doc, source_sha256="sha")


def test_no_missing_subgroup_or_price_ev_gate():
    doc = fixture()
    del doc["by_quality_availability"]["False"]
    with pytest.raises(ValueError, match="availability groups"):
        evaluate(doc, source_sha256="sha")


def test_no_fabricated_annual_conditional_scores():
    result = evaluate(fixture(), source_sha256="sha")
    assert result["validation_gates"]["year_specific_gated_holdout"] == "NOT_AVAILABLE_IN_AGGREGATE_SOURCE"
    assert "by_year" not in result
