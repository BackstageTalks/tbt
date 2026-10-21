from datetime import datetime, timedelta, timezone

import pytest

from scripts.audit_model_shadow_readonly import summarize, validate_cohort


def row(index=1, *, p_prod=0.4, p_chal=0.8, target=1, status="settled"):
    day = datetime(2026, 10, 9 + index, 12, tzinfo=timezone.utc)
    result = {
        "match_id": f"match-{index}",
        "tour": "ATP" if index % 2 else "WTA",
        "surface": "hard",
        "production_model_version": "champion",
        "challenger_model_version": "candidate",
        "captured_at": (day - timedelta(hours=2)).isoformat(),
        "scheduled_at": day.isoformat(),
        "status": status,
        "production_player1_probability": p_prod,
        "challenger_player1_probability": p_chal,
    }
    if status == "settled":
        result.update({
            "target_player1_win": target,
            "production_correct": (p_prod >= 0.5) == bool(target),
            "challenger_correct": (p_chal >= 0.5) == bool(target),
        })
    return result


def test_uses_same_pre_match_pair_and_never_promotes():
    report = summarize([row()], "champion", "candidate")
    assert report["cohort"]["settled"] == 1
    assert report["paired"]["challenger_only_correct"] == 1
    assert report["overall"]["champion"]["accuracy"] == 0
    assert report["overall"]["challenger"]["accuracy"] == 1
    assert report["status"] == "INSUFFICIENT_PAIRED_SAMPLE"
    assert report["gate"]["automatic_promotion"] is False
    assert report["roi_yield_status"].startswith("NOT_EVALUABLE")


def test_different_model_pair_is_ignored():
    unrelated = {**row(2), "challenger_model_version": "other"}
    report = summarize([row(), unrelated], "champion", "candidate")
    assert report["cohort"]["captured"] == 1


def test_starts_only_before_fixture():
    invalid = {**row(), "captured_at": row()["scheduled_at"]}
    with pytest.raises(ValueError, match="after scheduled"):
        validate_cohort([invalid], "champion", "candidate")


def test_duplicate_identity_is_blocked():
    with pytest.raises(ValueError, match="Duplicate"):
        validate_cohort([row(), row()], "champion", "candidate")


def test_wrong_settlement_is_not_accepted():
    invalid = {**row(), "production_correct": True}
    with pytest.raises(ValueError, match="disagreement"):
        validate_cohort([invalid], "champion", "candidate")


@pytest.mark.parametrize("prob", [0, 1, float("nan"), float("inf"), -0.2])
def test_bad_probabilities_rejected(prob):
    invalid = {**row(), "challenger_player1_probability": prob}
    with pytest.raises(ValueError, match="Invalid pre-match"):
        validate_cohort([invalid], "champion", "candidate")


def test_empty_cohort_is_honestly_insufficient():
    result = summarize([], "champion", "candidate")
    assert result["cohort"]["settled"] == 0
    assert result["status"] == "INSUFFICIENT_PAIRED_SAMPLE"
    assert result["overall"] == {}


def test_pending_not_scored_as_loss():
    report = summarize([row(status="pending")], "champion", "candidate")
    assert report["cohort"]["pending"] == 1
    assert report["cohort"]["settled"] == 0


def test_isolation_and_no_fit_contract():
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "scripts/audit_model_shadow_readonly.py").read_text()
    assert "build_shadow_report(" in script
    assert "read_only" not in script or "readonly" in __name__
    assert "upload_bundle(" not in script and "upload(" not in script
    assert ".fit(" not in script and "train_from_matches(" not in script
    wf = (Path(__file__).resolve().parents[1] / ".github/workflows/model-shadow-evaluation-readonly.yml").read_text()
    assert "workflow_dispatch" in wf
    assert "actions/upload-artifact" in wf
    assert "model-shadow-audit" in wf


def test_paired_uncertainty_is_reproducible_and_not_a_promotion():
    from scripts.audit_model_shadow_readonly import _paired_confidence

    rows = [
        row(1, p_prod=.4, p_chal=.8, target=1),
        row(2, p_prod=.8, p_chal=.4, target=1),
    ]
    first = _paired_confidence(rows, samples=100)
    assert first == _paired_confidence(rows, samples=100)
    assert first["n"] == 2
    assert first["challenger_only_correct"] == 1
    assert first["champion_only_correct"] == 1
    assert first["mcnemar_exact_two_sided_p"] == 1.0
    assert first["paired_deltas"]["accuracy_pp"]["delta"] == 0.0
    assert first["settled_utc_days"] == 2
    assert _paired_confidence([])["status"] == "INSUFFICIENT"


def test_strict_atp_wta_screen_does_not_confuse_aggregate_green_with_release():
    from scripts.audit_model_shadow_readonly import _segment_release_screen

    def values(acc, log, brier, ece):
        return {"n": 60, "accuracy": acc, "log_loss": log, "brier_score": brier, "ece_10": ece}
    data = {"tour": {
        "ATP": {
            "champion": values(.70, .59, .20, .06),
            "challenger": values(.68, .58, .19, .05)},
        "WTA": {
            "champion": values(.67, .56, .19, .04),
            "challenger": values(.72, .54, .18, .07)},
    }}
    actual = _segment_release_screen([], {"ready_for_promotion_review": True}, data)
    assert actual["status"] == "SHADOW_SEGMENTS_PASS"
    assert actual["reasons"] == []
    data["tour"]["WTA"]["challenger"]["log_loss"] = .69
    blocked = _segment_release_screen([], {"ready_for_promotion_review": True}, data)
    assert blocked["status"] == "SHADOW_SEGMENT_REGRESSIONS"
    assert "wta_log_loss_material_regression" in blocked["reasons"]
    assert actual["production_change_authorized"] is False
    assert "NOT_EVALUATED" in actual["official_promotion"]
    assert _segment_release_screen([], {"ready_for_promotion_review": False}, data)["reasons"][0] == "aggregate_shadow_gate_not_met"


def test_segment_sample_missing_is_a_blocker():
    from scripts.audit_model_shadow_readonly import _segment_release_screen

    actual = _segment_release_screen([], {"ready_for_promotion_review": True}, {"tour": {}})
    assert "atp_sample_below_50_or_unpaired" in actual["reasons"]
    assert "wta_sample_below_50_or_unpaired" in actual["reasons"]
