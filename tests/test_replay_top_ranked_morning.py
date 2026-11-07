"""Read-only morning TOP ranking regression: one market, no fabricated outcomes."""
from replay_top_ranked_morning import compare_days, is_original_value, market_card, score


def r(event, *, p=.70, odds=1.6, other=2.6, depth=1.0,
      surface=10, section=None, correct=True, quote_ok=True):
    item = {
        "event":event, "day":"2026-11-03", "public":p, "odds":odds,
        "depth":depth,"min_surface":surface,"quote_ok":quote_ok,
        "section":section,"correct":correct,
        "two_way":{"player1_odds":odds,"player2_odds":other,
                   "player1_implied_probability":(1/odds)/(1/odds+1/other)},
    }
    frozen={"event_id":event,"winner_id":"p1","player1":{"id":"p1"},
            "player2":{"id":"p2"},"samples":{
                "player1_matches":30,"player2_matches":40,
                "player1_surface_matches":surface,
                "player2_surface_matches":surface},
            "two_way_market":item["two_way"]}
    item["ranking_card"]=market_card(item,frozen)
    return item


def test_rank_3_and_5_are_internal_positions_in_existing_top():
    rows=[r(f"event{i}",p=.86-.02*i) for i in range(7)]
    report=compare_days({"v7.2.1":{"2026-11-03":rows}})
    model=report["models"]["v7.2.1"]
    assert report["market_output"]=="top_daily_picks_only"
    assert report["no_new_offer"] is True
    assert model["totals"]["ranked_top1"]["candidates"]==1
    assert model["totals"]["ranked_top3"]["candidates"]==3
    assert model["totals"]["ranked_top5"]["candidates"]==5
    assert model["totals"]["ranked_top5"]["wins"]==5
    assert model["blockers"]=={}


def test_value_priority_and_data_backup_do_not_fake_empty_prices():
    rows=[
        r("value",p=.80,odds=1.90,other=2.00),
        r("core",p=.78),
        r("backup",p=.70,depth=.76,surface=3),
        r("backup2",p=.71,depth=.75,surface=4),
        r("unpriced",p=.98,quote_ok=False),
        r("too_shallow",p=.90,depth=.50),
        r("under_150",p=.90,odds=1.49),
    ]
    assert is_original_value(rows[0])
    out=compare_days({"v7.2.1":{"2026-11-03":rows}})["models"]["v7.2.1"]
    day=out["days"]["2026-11-03"]
    assert day["ranked_top5"]["candidates"]==3
    assert day["used_backup"]==2
    assert day["shortfall"]==0
    assert day["no_valid_price"]==1


def test_pending_canonical_outcome_is_not_a_recorded_loss():
    rows=[r("known",correct=True),r("pending",correct=None)]
    model=compare_days({"v7.2.1":{"2026-11-03":rows}})["models"]["v7.2.1"]
    top=model["totals"]["ranked_top3"]
    assert top["candidates"]==2
    assert (top["settled"],top["wins"],top["losses"],top["pending_or_unmatched"])==(1,1,0,1)
    assert model["blockers"]["days_below_3"]==1


def test_new_only_and_old_only_are_separate_from_public_issuance():
    rows=[
        r("existing",p=.83,section="top_daily"),
        r("removed",p=.59,section="top_daily",correct=False),
        r("new",p=.80,section=None),
    ]
    model=compare_days({"v7.2.1":{"2026-11-03":rows}})["models"]["v7.2.1"]
    assert model["totals"]["both"]["candidates"]==1
    assert model["totals"]["old_only"]["candidates"]==1
    assert model["totals"]["new_only"]["candidates"]==1
    assert model["totals"]["original_snapshot_top"]["candidates"]==2
    assert model["totals"]["ranked_top5"]["candidates"]==2
