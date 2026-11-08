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
