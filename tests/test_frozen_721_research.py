"""Frozen v7.2.1 provenance and anti-leakage regression tests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest

from tbt.services.frozen_721_research import (
    FROZEN_721_MODEL_SHA256, FROZEN_721_TAG, FROZEN_721_VERSION,
    research_frozen_721, validate_frozen_evidence,
)

PROD = "v201-20260925T204608601094Z"


def evidence(*, days=8, per_day=80):
    rows = []
    start = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    for day in range(days):
        scheduled = start + timedelta(days=day)
        for i in range(per_day):
            target = int((i * 13 + day * 7) % 10 < 6)
            rows.append({
                "match_id": f"721-{day}-{i}",
                "player1_id": "a", "player2_id": "b",
                "production_model_version": PROD,
                "challenger_model_version": FROZEN_721_VERSION,
                "tour": "ATP" if i % 2 else "WTA",
                "scheduled_at": scheduled.isoformat(),
                "captured_at": (scheduled - timedelta(hours=2)).isoformat(),
                "settled_at": (scheduled + timedelta(hours=10)).isoformat(),
                "status": "settled",
                "result_winner_id": "a" if target else "b",
                "target_player1_win": target,
                "production_player1_probability": 0.64 if i % 3 else 0.33,
                "challenger_player1_probability": 0.72 if i % 3 else 0.25,
            })
    return {"source": {
        "candidate_tag": FROZEN_721_TAG,
        "candidate_version": FROZEN_721_VERSION,
        "candidate_model_sha256": FROZEN_721_MODEL_SHA256,
        "production_version": PROD,
        "provider_requests": 0,
    }, "rows": rows}


def test_frozen_pair_is_diagnostic_and_immutable():
    payload = evidence()
    original = deepcopy(payload)
    result = research_frozen_721(payload, production_version=PROD)
    assert result["status"] == "RESEARCH_EVALUATED"
    assert result["fit_rows"] == 320
    assert result["evaluation_rows"] == 320
    assert result["cohort_counts"]["settled"] == 640
    assert result["not_a_production_decision"] is True
    assert result["automatic_promotion"] is False
    assert result["provider_requests"] == 0
    assert payload == original


@pytest.mark.parametrize("mutate,expected", [
    (lambda p: p["source"].update(candidate_tag="tbt-model-candidate-v1"), "wrong_frozen_721_artifact"),
    (lambda p: p["source"].update(candidate_model_sha256="0"*64), "wrong_frozen_721_artifact"),
    (lambda p: p["source"].update(provider_requests=1), "evidence_must_not_spend_provider_requests"),
    (lambda p: p["rows"][0].update(challenger_model_version="old-shadow"), "foreign_model_pair_in_frozen_cohort"),
    (lambda p: p["rows"][0].update(captured_at=p["rows"][0]["scheduled_at"]), "prediction_not_captured_before_match"),
    (lambda p: p["rows"][0].update(settled_at=p["rows"][0]["captured_at"]), "settlement_not_after_fixture"),
    (lambda p: p["rows"][0].update(result_winner_id="different"), "settled_winner_identity_mismatch"),
    (lambda p: p["rows"][0].update(target_player1_win=1 - p["rows"][0]["target_player1_win"]), "settled_target_identity_mismatch"),
    (lambda p: p["rows"][0].update(challenger_player1_probability=float("nan")), "invalid_challenger_probability"),
    (lambda p: p["rows"].append(deepcopy(p["rows"][0])), "duplicate_match_id_in_frozen_cohort"),
    (lambda p: p["rows"][0].pop("player1_id"), "missing_or_ambiguous_match_identity"),
])
def test_bad_frozen_evidence_fails_closed(mutate, expected):
    payload = evidence()
    mutate(payload)
    with pytest.raises(ValueError, match=expected):
        validate_frozen_evidence(payload, production_version=PROD)


def test_prospective_scorecard_reports_actual_pair_and_surface_gaps():
    original = evidence(days=1, per_day=4)
    rows = original["rows"]
    # Expected: candidate loses two separate paired orientations vs champion.
    scores = [(0.8, 0.6, 1), (0.7, 0.2, 1),
              (0.2, 0.9, 0), (0.2, 0.1, 0)]
    for r, (p, q, truth) in zip(rows, scores):
        r.update({
            "production_player1_probability": p,
            "challenger_player1_probability": q,
            "target_player1_win": truth,
            "result_winner_id": "a" if truth else "b",
        })
    rows[0]["surface"] = "hard"
    rows[1]["surface"] = "unknown"
    rows[2]["surface"] = ""
    rows[3]["surface"] = "future-looking-surface-label"
    untouched = deepcopy(original)
    report = research_frozen_721(original, production_version=PROD)
    score = report["prospective_diagnostics"]
    assert original == untouched
    assert score["status"] == "PROSPECTIVE_DIAGNOSTIC_NOT_MODEL_SELECTION"
    assert score["overall"]["n"] == 4
    assert score["overall"]["champion"]["correct"] == 4
    assert score["overall"]["candidate"]["correct"] == 2
    assert score["overall"]["champion_only_correct"] == 2
    assert score["overall"]["candidate_only_correct"] == 0
    assert score["tour"]["ATP"]["n"] == 2
    assert score["tour"]["WTA"]["n"] == 2
    assert score["coverage"]["by_surface"]["hard"] == 1
    assert score["coverage"]["by_surface"]["unknown"] == 3
    assert score["coverage"]["known_surface_rate"] == .25
    assert "candidate_accuracy_below_champion" in score["review_blockers"]
    assert "prematch_surface_coverage_below_80_percent" in score["review_blockers"]
    assert score["automatic_promotion"] is False
    assert score["retraining_or_recalibration_performed"] is False
    assert score["next_model_requires_independent_chronological_holdout"] is True


def test_unsettled_rows_are_counted_for_coverage_never_model_accuracy():
    original = evidence(days=1, per_day=2)
    settled, pending = original["rows"]
    pending["status"] = "pending"
    pending.pop("settled_at")
    pending.pop("result_winner_id")
    pending.pop("target_player1_win")
    pending["surface"] = "clay"
    settled["surface"] = "unknown"
    report = research_frozen_721(original, production_version=PROD)
    scores = report["prospective_diagnostics"]
    assert scores["overall"]["n"] == 1
    assert scores["coverage"]["total_excluding_repeated_snapshots"] == 2
    assert scores["coverage"]["by_surface"]["clay"] == 1
    assert scores["coverage"]["unknown_surface_settled"] == 1
    assert scores["coverage"]["unknown_surface_pending"] == 0
    assert scores["surface"]["clay"]["n"] == 0
    assert scores["surface"]["unknown"]["n"] == 1
    assert scores["review_blockers"]
    assert report["automatic_promotion"] is False


def test_not_enough_days_does_not_claim_calibration_pass():
    report = research_frozen_721(evidence(days=2), production_version=PROD)
    assert report["status"] == "INSUFFICIENT_TEMPORAL_EVIDENCE"
    assert report["automatic_promotion"] is False


def test_unsettled_prediction_cannot_contain_winner():
    p = evidence(days=1, per_day=1)
    row = p["rows"][0]
    row["status"] = "pending"
    row.pop("settled_at")
    with pytest.raises(ValueError, match="outcome_leaked_into_unsettled_row"):
        validate_frozen_evidence(p, production_version=PROD)
    row.pop("target_player1_win")
    _, counts = validate_frozen_evidence(p, production_version=PROD)
    assert counts["pending"] == 1
