from copy import deepcopy
from datetime import datetime, timezone

import pytest
from test_market_selection import row
from tbt.services.market_selection import select_market_sections, build_selection_candidate_snapshot


def pick(event, p=.80, competition="ATP", odds=1.6, other=2.6):
    card=row(event,p,odds,other,depth=1.0)
    card["competition"]=competition
    card["tour"]="WTA" if competition.startswith("WTA") else "ATP"
    return card


def ids(output):
    return [r["event_id"] for r in output["top_daily_picks"]]


def test_main_tours_reach_70_before_using_itf_to_fill_target():
    rows=[pick("itf",.93,"ITF Men"),pick("wta",.70,"WTA"),
          pick("atp",.75),pick("challenger",.85,"Challenger")]
    out=select_market_sections(rows)
    assert ids(out)==["atp","wta","challenger"]
    assert out["market_selection"]["selection_counts"]["top_daily_shortfall"]==0


def test_itf_is_last_resort_not_entirely_removed():
    out=select_market_sections([pick("a",.78),pick("b",.75,"WTA"),pick("i",.80,"ITF Women")])
    assert ids(out)==["a","b","i"]


@pytest.mark.parametrize("p",[.60,.65,.6999])
def test_no_target_filling_below_70(p):
    out=select_market_sections([pick("low",p)])
    assert not ids(out)
    assert out["market_selection"]["selection_counts"]["top_daily_shortfall"]==3


@pytest.mark.parametrize("odds,other,section",[(1.50,2.5,"top_daily_picks"),(1.80,1.9,"top_daily_picks"),
    (1.81,1.9,"value_picks"),(2.20,1.5,"top_daily_picks")])
def test_exact_user_price_contract(odds,other,section):
    out=select_market_sections([pick("x",.80,odds=odds,other=other)])
    assert len(out[section])==1
    assert sum(len(out[k]) for k in ("prime_picks","top_daily_picks","value_picks"))==1


@pytest.mark.parametrize("field,value",[("created_at",None),("model_version",""),("competition",None),
    ("created_at","2026-09-07T13:00:00Z"),("winner_id","other")])
def test_new_top_requires_identity_and_prematch_prediction(field,value):
    card=pick("x");card[field]=value
    assert not ids(select_market_sections([card]))


def test_quote_time_and_evidence_do_not_relax_for_target():
    cases=[]
    card=pick("time");card["betting"].pop("captured_at");cases.append(card)
    card=pick("surface");card["quality"]["player1"]["surface_matches"]=3;cases.append(card)
    card=pick("depth",.95);card["data_depth"]=.75;cases.append(card)
    assert not ids(select_market_sections(cases))


def test_snapshot_keeps_policy_evidence_and_no_result():
    card=pick("x");card["result"]={"correct":True}
    out=build_selection_candidate_snapshot([card],generated_at=datetime(2026,9,7,8,tzinfo=timezone.utc))
    saved=out["rows"][0]
    assert saved["competition"]=="ATP" and saved["created_at"]==card["created_at"]
    assert saved["top_rejection_reasons"]==[] and "result" not in saved


def test_aces_random_prices_and_source_rows_remain_unchanged():
    aces=[{"event_id":"ace1","odds":1.6},{"event_id":"ace2","odds":1.8}]
    rows=[pick("a"),pick("b",.78),pick("c",.70)]
    before=deepcopy(rows)
    out=select_market_sections(rows,ace_picks=aces)
    assert out["ace_picks"]==aces and rows==before


def test_probability_wins_over_market_consensus_within_same_group():
    # Lower probability has a stronger bookmaker agreement, but must rank last.
    rows = [pick("lower", .81, odds=1.5, other=4.0),
            pick("higher", .89, odds=1.8, other=2.0),
            pick("middle", .85, "WTA", odds=1.7, other=2.1)]
    assert ids(select_market_sections(rows)) == ["higher", "middle", "lower"]


def test_secondary_probability_order_and_itf_only_fill_remaining_slots():
    rows = [pick("itf", .95, "ITF Men"), pick("secondary-low", .71, "Challenger"),
            pick("secondary-high", .88, "WTA 125"), pick("main", .70)]
    assert ids(select_market_sections(rows)) == ["main", "secondary-high", "secondary-low"]


@pytest.mark.parametrize("tournament", [
    "ITF M15 Monastir", "ITF M25 Antalya", "ITF M 15 Futures",
])
def test_m15_m25_top_hold_pending_calibration(tournament):
    card = pick("itf-risk", .71, "ITF Men", odds=2.70, other=1.50)
    card["tournament"] = tournament
    before = deepcopy(card)
    selected = select_market_sections([card])
    assert ids(selected) == []
    assert selected["market_selection"]["selection_counts"]["top_daily_shortfall"] == 3
    assert selected["market_selection"]["top_rejection_counts"][
        "itf_m15_m25_top_hold_pending_calibration"
    ] == 1
    assert card == before  # preserve source and existing issued records
    snap = build_selection_candidate_snapshot(
        [card], generated_at=datetime(2026, 11, 11, 6, tzinfo=timezone.utc)
    )
    assert "itf_m15_m25_top_hold_pending_calibration" in snap["rows"][0]["top_rejection_reasons"]
    assert snap["rows"][0]["selected_section"] is None


def test_m15_m25_hold_does_not_change_value_or_generic_itf_top():
    m15 = pick("value-m15", .71, "ITF Men", odds=1.91, other=1.95)
    m15["tournament"] = "ITF M15"
    normal_itf = pick("itf-other", .75, "ITF Women", odds=1.60)
    out = select_market_sections([m15, normal_itf])
    assert ids(out) == ["itf-other"]
    assert [x["event_id"] for x in out["value_picks"]] == ["value-m15"]


def test_m15_m25_hold_does_not_false_match_m150_or_main_tours():
    m150 = pick("itf-150", .75, "ITF Men")
    m150["tournament"] = "ITF M150"
    atp = pick("atp", .72, "ATP")
    out = select_market_sections([m150, atp])
    assert ids(out) == ["atp", "itf-150"]


def test_feature_availability_snapshot_is_not_a_calibration_claim():
    card = pick("availability")
    evidence = {
        "historical_count_depth": 1.0,
        "serve_return_known_both": False,
        "surface_serve_return_known_both": False,
        "rank_values_known_both": False,
        "meaning": "pre_match_feature_availability_not_calibrated_confidence",
    }
    card["quality"]["feature_evidence"] = evidence
    snap = build_selection_candidate_snapshot(
        [card], generated_at=datetime(2026, 11, 11, 6, tzinfo=timezone.utc)
    )
    assert snap["rows"][0]["feature_evidence"] == evidence
    assert snap["rows"][0]["data_depth"] == 1.0


@pytest.mark.parametrize("competition,tournament,odds,other", [
    ("ITF Men", "ITF M50 Test", 2.50, 1.50),
    ("ITF Women", "ITF W35 Heraklion", 2.70, 1.52),
])
def test_severe_market_outsider_conflict_held_from_new_top(competition, tournament, odds, other):
    card = pick("model-market-reversal", .718, competition, odds=odds, other=other)
    card["tournament"] = tournament
    before = deepcopy(card)
    output = select_market_sections([card])
    assert ids(output) == []
    assert output["market_selection"]["top_rejection_counts"]["top_unverified_market_outsider_conflict"] == 1
    assert output["market_selection"]["selection_counts"]["top_daily_shortfall"] == 3
    audit = build_selection_candidate_snapshot(
        [card], generated_at=datetime(2026, 11, 11, 8, tzinfo=timezone.utc)
    )
    assert "top_unverified_market_outsider_conflict" in audit["rows"][0]["top_rejection_reasons"]
    assert audit["rows"][0]["selected_section"] is None
    assert card == before


def test_high_odds_not_a_ceiling_when_market_agrees():
    card = pick("qualified-longer-price", .80, odds=2.20, other=2.60)
    output = select_market_sections([card])
    assert ids(output) == ["qualified-longer-price"]
    assert "top_unverified_market_outsider_conflict" not in output["market_selection"]["top_rejection_counts"]


def test_small_outsider_difference_still_eligible():
    # Exactly 1.80 stays in TOP; >1.80 with nearly equal prices belongs
    # to VALUE by explicit product priority, not by market safety.
    card = pick("small-difference", .71, odds=1.80, other=1.75)
    output = select_market_sections([card])
    assert ids(output) == ["small-difference"]


def test_outsider_top_hold_does_not_modify_prime_value_or_aces():
    outsider = pick("outsider", .718, odds=2.50, other=1.50)
    value = pick("value", .71, odds=1.91, other=1.95)
    prime = pick("prime", .71, odds=1.30, other=3.50)
    aces = [{"event_id": "ace", "odds": 1.75}]
    originals = deepcopy([outsider, value, prime])
    output = select_market_sections([outsider, value, prime], ace_picks=aces)
    assert ids(output) == []
    assert [r["event_id"] for r in output["value_picks"]] == ["value"]
    assert [r["event_id"] for r in output["prime_picks"]] == ["prime"]
    assert output["ace_picks"] == aces
    assert [outsider, value, prime] == originals


def test_high_odds_atp_selection_unchanged_by_itf_precaution():
    atp = pick("atp-outsider", .718, "ATP", odds=2.50, other=1.50)
    output = select_market_sections([atp])
    assert ids(output) == ["atp-outsider"]


def test_itf_favorite_not_removed_by_market_precaution():
    itf = pick("itf-favorite", .718, "ITF Women", odds=1.52, other=2.50)
    output = select_market_sections([itf])
    assert ids(output) == ["itf-favorite"]
