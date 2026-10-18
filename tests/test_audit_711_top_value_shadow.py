"""Contract tests: no hindsight, invented odds, player mixups or unissued bets."""
from copy import deepcopy
from audit_711_top_value_shadow import CHAMPION, CANDIDATE, evaluate

PUB="2026-10-16T09:00:00Z"
START="2026-10-16T13:00:00Z"
SNAP="2026-10-16T08:00:00Z"


def sample(section="top_daily", odd=1.8, correct=True):
    return {
        "event_id":"event1", "match_id":"match1", "tour":"ATP", "scheduled_at":START,
        "player1":{"id":"a"}, "player2":{"id":"b"},
        "market_publications":[{"section":section,"market":"match_winner","selection_id":"a",
                                "issued_at":PUB,"odds":odd,"publication_status":"published",
                                "result":{"scheduled_at":START,"correct":correct}}]
    }


def shadow():
    return {"event_id":"event1","match_id":"match1","tour":"ATP","scheduled_at":START,
            "captured_at":SNAP,"player1_id":"a","player2_id":"b","status":"settled",
            "target_player1_win":1,"production_model_version":CHAMPION,
            "challenger_model_version":CANDIDATE,
            "production_player1_probability":.63,"challenger_player1_probability":.82}


def test_exact_pair_real_odds_and_threshold():
    r=evaluate([sample()],[shadow()])
    assert r["matched_unique"]==1
    assert abs(r["groups"]["all"]["baseline_same_fixed_picks"]["roi"]-.8)<1e-12
    assert r["groups"]["all"]["fixed_offer_if_minimum_predicted_probability"]["0.8"]["champion"]["n"]==0
    assert r["groups"]["all"]["fixed_offer_if_minimum_predicted_probability"]["0.8"]["candidate"]["n"]==1
    assert r["model_promoted"] is False


def test_opposite_side_keeps_probability_orientation():
    a=sample(correct=False);a["market_publications"][0]["selection_id"]="b"
    r=evaluate([a],[shadow()])
    assert r["matched_unique"]==1
    assert abs(r["groups"]["all"]["probability"]["candidate"]["mean_probability"]-.18)<1e-12


def test_shadow_captured_after_publication_rejected():
    r=shadow();r["captured_at"]="2026-10-16T10:00:00Z"
    assert evaluate([sample()],[r])["matched_unique"]==0


def test_wrong_candidate_pair_rejected():
    r=shadow();r["challenger_model_version"]="other"
    assert evaluate([sample()],[r])["matched_unique"]==0


def test_odds_below_limit_rejected():
    assert evaluate([sample(odd=1.49)],[shadow()])["source_issued"]==0


def test_result_disagreement_rejected():
    r=evaluate([sample(correct=False)],[shadow()])
    assert r["unmatched_reasons"]["settlement_disagreement"]==1


def test_identity_mismatch_rejected():
    r=shadow();r["player2_id"]="other"
    assert evaluate([sample()],[r])["unmatched_reasons"]["player_identity_mismatch"]==1


def test_duplicate_section_not_double_counted():
    p=sample();p["market_publications"].append(deepcopy(p["market_publications"][0]))
    r=evaluate([p],[shadow()])
    assert r["source_issued"]==1
    assert r["source_diagnostics"]["duplicate_issued_selection"]==1


def test_cross_section_fixed_exposure_not_double_counted():
    a=sample()
    a["market_publications"].append(sample("value")["market_publications"][0])
    r=evaluate([a],[shadow()])
    assert r["source_issued"]==2 and r["matched_unique"]==1
    assert r["unmatched_reasons"]["cross_section_same_pick_exposure"]==1


def test_no_matching_forward_shadow_returns_no_roi():
    r=evaluate([sample()],[])
    assert r["status"]=="INSUFFICIENT_MATCHED_PUBLISHED_PICKS"
    assert r["groups"]["all"]["baseline_same_fixed_picks"]["roi"] is None


def test_no_future_unsettled_or_inplay_publish():
    a=sample();a["market_publications"][0]["issued_at"]="2026-10-17T14:00:00Z"
    b=sample();b["market_publications"][0]["result"]["correct"]=None
    c=sample();c["scheduled_at"]="2026-10-20T13:00:00Z";c["market_publications"][0]["result"]["scheduled_at"]=c["scheduled_at"]
    assert evaluate([a,b,c],[shadow()])["source_issued"]==0
