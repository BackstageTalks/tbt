"""Deterministic read-only tests for proposed TOP selection on the full slate."""
from datetime import datetime, timezone

from replay_top_strategy import evaluate, prematch_category, score, strict_top


def candidate(event, *, confidence=.88, depth=1.0, odds=1.65, opponent=2.45,
              competition="ATP250", tour="ATP", section=None,
              quote="2026-11-02T06:58:00+00:00"):
    return {
        "event_id": event, "scheduled_at": "2026-11-02T12:00:00+00:00",
        "tour": tour, "tournament": "Frozen Provider Tournament",
        "competition": competition, "surface": "hard", "model_version": "v7.2.1",
        "winner_id": "a",
        "player1": {"id": "a", "rank": 25, "probability": confidence},
        "player2": {"id": "b", "rank": 30, "probability": 1-confidence},
        "raw_model_probability": confidence,
        "blinq_probability": .5 + (confidence-.5)*depth,
        "data_depth": depth,
        "samples": {"player1_matches": 30, "player2_matches": 30,
                    "player1_surface_matches": 10, "player2_surface_matches": 10},
        "priced": True,
        "betting": {"selection_id": "a", "odds": odds, "captured_at": quote},
        "two_way_market": {"player1_odds": odds, "player2_odds": opponent,
                           "captured_at": quote},
        "selected_section": section,
    }


def finished(event, *, winner="a", tour="ATP"):
    return {"match_id": event, "player1_id": "a", "player2_id": "b",
            "winner_id": winner, "status": "finished", "tour": tour,
            "scheduled_at": "2026-11-02T12:00:00+00:00",
            "provider_context_json": {}}


def snapshot(rows):
    return {"schema": 1, "generated_at": "2026-11-02T07:00:00+00:00",
            "scope": {"post_match_fields_excluded": True}, "rows": rows}


def test_competition_classification_never_infers_atp_main_from_generic_atp_tour():
    assert prematch_category(candidate("a", competition="ATP250")) == "ATP_MAIN"
    assert prematch_category(candidate("b", competition="WTA500", tour="WTA")) == "WTA_MAIN"
    assert prematch_category(candidate("c", competition="ITF M15")) == "ITF"
    assert prematch_category(candidate("d", competition="WTA125", tour="WTA")) == "WTA125"
    assert prematch_category(candidate("e", competition="Challenger")) == "CHALLENGER"
    assert prematch_category(candidate("f", competition="unknown")) == "UNKNOWN"


def test_fixed_top_no_quota_no_oversized_price_cap_and_value_priority():
    rows = [
        candidate("main-atp", confidence=.88),
        candidate("main-wta", confidence=.86, competition="WTA250", tour="WTA"),
        candidate("itf", confidence=.90, competition="ITF M15"),
        candidate("above180", confidence=.90, odds=2.10, opponent=3.10),
        candidate("value180", confidence=.90, odds=1.80, opponent=2.00),
        candidate("below80", confidence=.79),
        candidate("short", confidence=.90, odds=1.49),
        candidate("shallow", confidence=.90, depth=.50),
    ]
    outcomes = [finished(r["event_id"], tour=r["tour"]) for r in rows]
    result = evaluate([snapshot(rows)], outcomes)["models"]["v7.2.1"]
    # 1.80 + <=15% gap belongs to VALUE; >1.80 + large gap still TOP.
    assert result["strict_80_all_tours"]["candidate_count"] == 4
    assert result["strict_80_verified_atp_wta_only"]["candidate_count"] == 3
    assert result["strict_80_by_prematch_competition"]["ITF"]["candidate_count"] == 1
    assert result["per_day"]["2026-11-02"]["strict_80_all_tours"]["wins"] == 4


def test_exact_same_day_overlap_explains_unequal_candidate_counts():
    rows = [
        candidate("kept", confidence=.85, section="top_daily"),
        candidate("removed", confidence=.75, section="top_daily"),
        candidate("new", confidence=.83, section=None),
    ]
    results = [finished("kept"), finished("removed", winner="b"), finished("new")]
    reported = evaluate([snapshot(rows)], results)["models"]["v7.2.1"]
    cohorts = reported["exact_same_offer_reconciliation"]
    assert cohorts["both"]["candidate_count"] == 1
    assert cohorts["both"]["wins"] == 1
    assert cohorts["original_only"]["candidate_count"] == 1
    assert cohorts["original_only"]["losses"] == 1
    assert cohorts["strict_only"]["candidate_count"] == 1
    assert cohorts["strict_only"]["wins"] == 1
    assert reported["original_candidate_top"]["candidate_count"] == 2
    assert reported["strict_80_all_tours"]["candidate_count"] == 2


def test_overlap_pending_is_not_inflated_as_loss():
    rows = [
        candidate("kept", confidence=.85, section="top_daily"),
        candidate("new", confidence=.83, section=None),
    ]
    reported = evaluate([snapshot(rows)], [finished("kept")])["models"]["v7.2.1"]
    assert reported["exact_same_offer_reconciliation"]["both"]["settled"] == 1
    assert reported["exact_same_offer_reconciliation"]["strict_only"]["settled"] == 0
    assert reported["exact_same_offer_reconciliation"]["strict_only"]["pending_or_unmatched"] == 1


def test_funnel_explains_all_slate_quality_price_and_value_rejections():
    rows = [
        candidate("strong", confidence=.84, section="top_daily"),
        candidate("weak", confidence=.79),
        candidate("unpriced", confidence=.90, odds=1.49),
        candidate("shallow", confidence=.90, depth=.50),
        candidate("value", confidence=.90, odds=1.90, opponent=2.00),
    ]
    report = evaluate([snapshot(rows)], [finished(r["event_id"]) for r in rows])
    f = report["models"]["v7.2.1"]["eligibility_funnel"]
    assert f["candidate_rows"] == 5
    assert f["quote_valid"] == 5
    assert f["quote_below_min_1_50"] == 1
    assert f["odds_ge_1_50"] == 4
    assert f["quality_gate_rejected"] == 1
    assert f["below_fixed_80_probability"] == 1
    assert f["VALUE_claims_precedence"] == 1
    assert f["strict_TOP_pass"] == 1


def test_funnel_captures_unknown_category_without_main_tour_inference():
    report = evaluate([snapshot([
        candidate("unknown", competition="unknown", tour="ATP"),
        candidate("itf", competition="ITF M25", tour="ATP"),
    ])], [finished("unknown"), finished("itf")])
    model = report["models"]["v7.2.1"]
    assert model["eligibility_funnel_by_pre_match_competition"]["UNKNOWN"]["candidate_rows"] == 1
    assert model["eligibility_funnel_by_pre_match_competition"]["ITF"]["candidate_rows"] == 1
    assert model["strict_80_verified_atp_wta_only"]["candidate_count"] == 0


def test_one_or_zero_top_is_not_filled_from_70_to_79():
    rows = [candidate("strong", confidence=.82),
            candidate("weak79", confidence=.79),
            candidate("weak70", confidence=.70)]
    report = evaluate([snapshot(rows)], [finished(r["event_id"]) for r in rows])
    assert report["models"]["v7.2.1"]["strict_80_all_tours"]["candidate_count"] == 1
    none = [candidate("weak79", confidence=.79), candidate("weak70", confidence=.70)]
    report = evaluate([snapshot(none)], [finished(r["event_id"]) for r in none])
    assert report["models"]["v7.2.1"]["strict_80_all_tours"]["candidate_count"] == 0


def test_unknown_competition_remains_unknown_even_if_outcome_has_atp_level():
    rows = [candidate("no-level", competition="unknown", tour="ATP")]
    settled = [finished("no-level")]
    settled[0]["tournament_level"] = "ATP1000"  # post-match leakage bait
    report = evaluate([snapshot(rows)], settled)["models"]["v7.2.1"]
    assert report["strict_80_all_tours"]["candidate_count"] == 1
    assert report["strict_80_verified_atp_wta_only"]["candidate_count"] == 0
    assert report["strict_80_by_prematch_competition"]["UNKNOWN"]["candidate_count"] == 1


def test_late_quote_cannot_be_used_to_prove_top_hit_rate():
    row = candidate("late", quote="2026-11-02T12:01:00+00:00", section="top_daily")
    report = evaluate([snapshot([row])], [finished("late")])["models"]["v7.2.1"]
    assert report["strict_80_all_tours"]["candidate_count"] == 0
    assert report["original_candidate_top"]["candidate_count"] == 0


def test_ambiguous_canonical_identity_is_never_called_a_win():
    row = candidate("different-players")
    outcome = finished("different-players")
    outcome["player2_id"] = "wrong-person"
    report = evaluate([snapshot([row])], [outcome])["models"]["v7.2.1"]
    metrics = report["strict_80_all_tours"]
    assert metrics["candidate_count"] == 1
    assert metrics["settled"] == 0
    assert metrics["pending_or_unmatched"] == 1
    assert metrics["hit_rate"] is None


def test_one_unit_profit_uses_only_settled_quoted_winners():
    rows = [dict(odds=1.7, correct=True),
            dict(odds=2.1, correct=False),
            dict(odds=1.8, correct=None)]
    s = score(rows)
    assert s["candidate_count"] == 3
    assert (s["wins"], s["losses"], s["pending_or_unmatched"]) == (1, 1, 1)
    assert abs(s["hypothetical_profit_1u"] + .3) < 1e-12
    assert abs(s["hypothetical_roi"] + .15) < 1e-12
