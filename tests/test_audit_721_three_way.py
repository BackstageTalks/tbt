"""Contract tests of the no-provider, no-training 721 triple evidence gate."""
import copy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pytest
from audit_721_three_way import report, prepare, metrics


def fixture():
    row = dict(
        match_id="fixture-1", tour="ATP", surface="hard", player1_id="100",
        player2_id="200", status="settled",
        production_model_version="champ-v201",
        challenger_model_version="v7.2.1",
        production_player1_probability=.62, challenger_player1_probability=.73,
        scheduled_at="2026-10-01T15:00:00Z",
        captured_at="2026-09-30T15:00:00Z",
        settled_at="2026-10-01T19:00:00Z",
        target_player1_win=1, result_winner_id="100",
    )
    paired = {
        "source": {"production_version":"champ-v201", "candidate_version":"v7.2.1",
                   "candidate_model_sha256":"abcdef12345", "candidate_tag":"frozen-signed"},
        "rows":[row]
    }
    research = {
        "source":{"model_version":"research-1", "model_sha256":"fedcba54321",
                  "training_end":"2026-08-01T00:00:00Z",
                  "calibration_end":"2026-09-01T00:00:00Z",
                  "input_release_sha256":"source-snapshot",
                  "mode":"RETROSPECTIVE_PIT_REPLAY"},
        "rows":[dict(match_id="fixture-1",tour="ATP",player1_id="100",
                     player2_id="200",feature_asof="2026-09-29T15:00:00Z",
                     generated_at="2026-10-24T00:00:00Z",
                     research_player1_probability=.8)]
    }
    return paired,research


def test_identical_fixtures_and_replay_are_scored_but_not_promoted():
    paired,research=fixture()
    r=report(paired,research)
    assert r["comparison_cohort"]["n"] == 1
    assert r["overall"]["research"]["accuracy"] == 1
    assert r["overall"]["candidate_721"]["accuracy"] == 1
    assert r["assessment"] == "RETROSPECTIVE_ONLY_NOT_PROSPECTIVE"
    assert r["production_mutated"] is False
    assert r["provider_requests"] == 0
    assert r["paired_accuracy_delta_ci95_vs_721"]["research"] is None


def test_mismatched_player_orientation_rejected():
    p,r=fixture()
    r["rows"][0]["player1_id"],r["rows"][0]["player2_id"]="200","100"
    with pytest.raises(ValueError,match="orientation_or_tour"):
        prepare(p,r)


def test_missing_research_fixture_rejected():
    p,r=fixture()
    r["rows"]=[]
    with pytest.raises(ValueError,match="missing_research"):
        prepare(p,r)


def test_duplicated_research_prediction_rejected():
    p,r=fixture()
    r["rows"].append(copy.deepcopy(r["rows"][0]))
    with pytest.raises(ValueError,match="ambiguous_research"):
        prepare(p,r)


def test_outcome_winner_identity_rejected():
    p,r=fixture()
    p["rows"][0]["target_player1_win"]=0
    with pytest.raises(ValueError,match="outcome_identity"):
        prepare(p,r)


def test_future_history_feature_rejected():
    p,r=fixture()
    r["rows"][0]["feature_asof"]="2026-10-01T16:00:00Z"
    with pytest.raises(ValueError,match="not_asof_original"):
        prepare(p,r)


def test_train_or_calibration_using_test_year_rejected():
    p,r=fixture()
    r["source"]["calibration_end"]="2026-10-02T00:00:00Z"
    with pytest.raises(ValueError,match="uses_test_time"):
        prepare(p,r)


def test_replay_cannot_forge_issuance():
    p,r=fixture()
    r["rows"][0]["issued_at"]="2026-09-29T15:00:00Z"
    with pytest.raises(ValueError,match="replay_must_not_fake"):
        prepare(p,r)


def test_issued_requires_issued_before_original_capture():
    p,r=fixture()
    r["source"]["mode"]="ISSUED_PREMATCH"
    r["rows"][0].pop("generated_at")
    r["rows"][0]["issued_at"]="2026-09-30T20:00:00Z"
    with pytest.raises(ValueError,match="not_issued_before"):
        prepare(p,r)
    r["rows"][0]["issued_at"]="2026-09-30T14:00:00Z"
    assert report(p,r)["assessment"]=="INSUFFICIENT_COHORT"


def test_no_false_high_confidence_when_empty():
    p,r=fixture()
    observed=prepare(p,r)
    assert metrics(observed,"champion")["high80"]["n"]==0
    assert metrics(observed,"champion")["high80"]["accuracy"] is None


def test_nonfinite_research_probability_rejected():
    p,r=fixture()
    r["rows"][0]["research_player1_probability"]=float("nan")
    with pytest.raises(ValueError,match="invalid_research"):
        prepare(p,r)


def test_unsettled_rows_cannot_create_evidence():
    p,r=fixture()
    p["rows"][0]["status"]="pending"
    with pytest.raises(ValueError,match="no_verified_settled"):
        prepare(p,r)
