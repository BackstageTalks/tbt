"""Portable regression coverage for the read-only frozen candidate evidence gate."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_calibration_run_evidence.py"
spec = importlib.util.spec_from_file_location("verify_calibration_run_evidence", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
SHA = "a" * 40


def proof():
    cert = {
        "application_sha": SHA, "run_id": "1234", "attempt": "1",
        "status": "VERIFIED_FULL_INPUTS_AND_ISOLATED_RESTORE",
        "all_assets_remotely_verified": 4, "canonical_mutated": False,
        "production_mutated": False, "provider_requests": 0,
        "champion_version": "champion", "champion_sha256": "b" * 64,
        "remote_manifest_sha256": "c" * 64,
        "champion_restore": {"status": "PASS", "restored_version": "champion",
                             "max_prediction_difference": 0.0},
    }
    leakage = {
        "status": "pass", "failed_checks": [], "checks": {"PIT": True},
        "rows": 300, "verified_feature_cache": {
            "run_id": "1234", "attempt": "1", "application_sha": SHA,
            "backup_manifest_sha256": "c" * 64, "rows": 300,
        },
    }
    report = {
        "data": {"holdout": 200},
        "evaluation_governance": {"holdout_fingerprint": "cohort"},
        "promotion_decision": {
            "production_version": "champion", "candidate_version": "candidate",
            "holdout_fingerprint": "cohort", "promotion_requested": False,
        },
        "production_holdout": {
            "n": 200, "accuracy": .65, "brier_score": .21,
            "log_loss": .61, "ece_10": .02,
        },
        "holdout": {
            "n": 200, "accuracy": .66, "brier_score": .20,
            "log_loss": .60, "ece_10": .03,
        },
        "context_calibration_holdout": {"groups": {"all": {
            "n": 200, "parent": {"brier": .205, "log_loss": .605},
            "candidate": {"brier": .20, "log_loss": .60},
        }}},
        "rank_reliability_holdout": {"groups": {
            "weekly_rank_pair_known": {"n": 0},
            "weekly_rank_pair_missing": {"n": 200},
        }},
        "evaluation_model": {"context_calibration_methods": ["main_atp"]},
        "rank_alignment": {"status": "PIT_WEEKLY_ALIGNED"},
        "subgroups": {"tour": {"wta": {"ece_10": .04}}},
        "production_subgroups": {"tour": {"wta": {"ece_10": .025}}},
        "top_market_validation": {
            "status": "NOT_EVALUATED", "promotion_ready_for_top": False,
        },
    }

    report["pit_evidence_holdout"] = {
        "status": "PAIRED_UNSEEN_HOLDOUT",
        "holdout_only": True,
        "never_select_on_holdout": True,
        "cohorts": {
            "stats_0_rank_0": {
                "n": 200,
                "candidate": {"n": 200, "accuracy": .66, "brier_score": .20,
                              "mean_confidence": .78},
                "champion": {"n": 200, "accuracy": .65, "brier_score": .21,
                             "mean_confidence": .76},
            },
            "stats_0_rank_1": {"n": 0, "candidate": None, "champion": None},
            "stats_1_rank_0": {"n": 0, "candidate": None, "champion": None},
            "stats_1_rank_1": {"n": 0, "candidate": None, "champion": None},
        },
    }
    return report, cert, leakage


def test_brier_improvement_does_not_excuse_ece_or_zero_rank_coverage():
    report, cert, leakage = proof()
    result = gate.analyze(report, cert, leakage, expected_commit=SHA)
    assert result["status"] == "BLOCKED_PRODUCTION_PROMOTION"
    assert result["verified_weekly_rank_holdout"] == {
        "known_both": 0, "missing": 200, "coverage": 0.0,
    }
    assert result["gates"]["proper_score_improvement"] is True
    assert result["gates"]["ece_nonregression"] is False
    assert result["gates"]["wta_ece_nonregression"] is False
    assert result["gates"]["verified_weekly_rank_holdout"] is False
    assert result["gates"]["real_top_issuance_validated"] is False


@pytest.mark.parametrize("part", [
    "wrong_source", "wrong_cache_source", "wrong_manifest", "wrong_champion",
    "leakage_failure",
])
def test_integrity_mismatch_never_produces_success(part):
    r, c, l = proof()
    if part == "wrong_source":
        c["application_sha"] = "f" * 40
    elif part == "wrong_cache_source":
        l["verified_feature_cache"]["application_sha"] = "f" * 40
    elif part == "wrong_manifest":
        l["verified_feature_cache"]["backup_manifest_sha256"] = "0" * 64
    elif part == "wrong_champion":
        r["promotion_decision"]["production_version"] = "wrong"
    else:
        l["failed_checks"] = ["future_leakage"]
    with pytest.raises(ValueError):
        gate.analyze(r, c, l, expected_commit=SHA)


def test_holdout_pairing_must_match():
    r, c, l = proof()
    r["production_holdout"]["n"] = 199
    with pytest.raises(ValueError, match="same-holdout"):
        gate.analyze(r, c, l, expected_commit=SHA)


def test_rank_groups_must_partition_same_holdout():
    r, c, l = proof()
    r["rank_reliability_holdout"]["groups"]["weekly_rank_pair_known"]["n"] = 3
    with pytest.raises(ValueError, match="partition"):
        gate.analyze(r, c, l, expected_commit=SHA)


def test_fake_top_pass_still_cannot_claim_prospective_validation():
    r, c, l = proof()
    r["top_market_validation"] = {"status": "PASS", "promotion_ready_for_top": True}
    result = gate.analyze(r, c, l, expected_commit=SHA)
    assert result["gates"]["new_prospective_top_validated"] is False
    assert result["status"] == "BLOCKED_PRODUCTION_PROMOTION"


def test_nonidentical_rollback_is_rejected():
    r, c, l = proof()
    c["champion_restore"]["max_prediction_difference"] = 0.0001
    with pytest.raises(ValueError, match="restoration"):
        gate.analyze(r, c, l, expected_commit=SHA)


def test_archive_cli_is_read_only_and_never_returns_a_promotion(tmp_path, capsys):
    r, c, l = proof()
    artifact = tmp_path / "proof.zip"
    with zipfile.ZipFile(artifact, "w") as z:
        for name, obj in zip(gate.FILES.values(), (r, c, l)):
            z.writestr(name, json.dumps(obj))
    output = tmp_path / "gate.json"
    assert gate.main(["--artifact", str(artifact), "--expected-commit", SHA,
                      "--out", str(output)]) == 0
    assert json.loads(output.read_text())["status"] == "BLOCKED_PRODUCTION_PROMOTION"
    assert not (tmp_path / "model.joblib").exists()


def test_quality_evidence_is_independent_of_count_depth():
    r, c, l = proof()
    audited = gate.analyze(r, c, l, expected_commit=SHA)
    quality = audited["feature_quality_holdout"]
    assert quality["status"] == "VERIFIED_DESCRIPTIVE_ONLY"
    assert quality["total"] == 200
    assert quality["paired_serve_return_available"] == 0
    assert quality["paired_weekly_ranks_available"] == 0
    assert quality["paired_both_available"] == 0
    assert quality["groups"]["stats_0_rank_0"]["candidate_confidence_minus_accuracy"] == pytest.approx(.12)
    assert quality["supported_group_brier_nonregression"] is True
    assert quality["training_or_publication_authorized"] is False


@pytest.mark.parametrize("corruption", ["count", "rank", "scores", "missing", "not_frozen"])
def test_untrusted_quality_cohorts_fail_closed(corruption):
    r, c, l = proof()
    evidence = r["pit_evidence_holdout"]
    if corruption == "count":
        evidence["cohorts"]["stats_0_rank_0"]["n"] = 199
    elif corruption == "rank":
        evidence["cohorts"]["stats_0_rank_0"]["n"] = 199
        evidence["cohorts"]["stats_0_rank_1"] = {
            "n": 1,
            "candidate": {"n": 1, "accuracy": 1., "brier_score": 0., "mean_confidence": .9},
            "champion": {"n": 1, "accuracy": 1., "brier_score": 0., "mean_confidence": .9},
        }
    elif corruption == "scores":
        evidence["cohorts"]["stats_0_rank_0"]["candidate"]["brier_score"] = .35
    elif corruption == "missing":
        del evidence["cohorts"]["stats_1_rank_1"]
    else:
        evidence["never_select_on_holdout"] = False
    with pytest.raises(ValueError):
        gate.analyze(r, c, l, expected_commit=SHA)
