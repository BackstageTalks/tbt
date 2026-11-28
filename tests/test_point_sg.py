from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest
from tbt.services import point_sg as sg
from tbt.services.point_shadow_results import summarize

NOW = datetime(2026,11,27,6,tzinfo=timezone.utc)
START = (NOW+timedelta(hours=2)).isoformat()


def inputs(market="games"):
    card = {"players":["a","b"],"event_id":"1","competition":"ATP","scheduled_at":START,
            "data_quality":"supported","set_score":{"value":{"2:0":.5,"0:2":.3,"2:1":.2}},
            "other_projections":{"value":{"total_games":{"19":.7,"20":.2,"24":.1}}}}
    line = 20 if market=="games" else 2.5
    row = {"market":market,"event_id":"1","player1":{"id":"a"},"player2":{"id":"b"},
           "scheduled_at":START, "captured_at":NOW.isoformat(),"odds_source":"rapidapi",
           "provider_id":1,"price_status":"priced_projection","odds":1.9, "market_line":line,
           "selection_id":f"{market}:over:{line}"}
    payload = {"markets":[{"marketName":"Total "+market, "choiceName":side,
                           "line":line,"decimalOdds":1.9} for side in ("Over","Under")]}
    return card,row,payload


def test_push_no_vig_and_fair_odds():
    card,row,payload = inputs()
    receipt = sg.freeze(card,row,payload,{},.60,NOW)
    tip = receipt["point"]
    assert tip["side"] == "under" and tip["p_win"] == .7
    assert tip["p_push"] == .2 and tip["fair_odds"] == pytest.approx(.8/.7)
    assert tip["edge"] == pytest.approx(.7/.8-.5)
    assert sg.grade(tip,20) == ("push",0)
    assert sg.grade(tip,24) == ("loss",-1)
    assert sg.grade(tip,19)[1] == pytest.approx(.9)
    assert sg.freeze(card,row,payload,{},.90,NOW)["point"] is None


def test_exact_scores_and_sets_from_same_book():
    card,row,payload = inputs("sets")
    row.update(odds_source="propline",provider_id=2,odds_bookmaker="Book")
    alt = {"bookmaker":"Book","captured_at":row["captured_at"],"payload":payload}
    receipt = sg.freeze(card,row,None,alt,.60,NOW)
    assert receipt["set_score"] == card["set_score"]["value"]
    assert receipt["point"]["p_win"] == pytest.approx(.8)
    assert sg.freeze(card,row,None,dict(alt,bookmaker="Other"),.60,NOW) is None
    assert sg.freeze(card,row,None,dict(alt,captured_at=START),.60,NOW) is None


def test_no_odds_itf_low_quality_and_late_freeze():
    card,row,payload = inputs()
    assert sg.freeze(card,row,None,{},.60,NOW) is None
    assert sg.freeze(card,row,payload,{},.60,datetime.fromisoformat(START)) is None
    assert sg.freeze(dict(card,competition="ITF"),row,payload,{},.6,NOW) is None
    assert sg.freeze(dict(card,data_quality="low"),row,payload,{},.6,NOW)["point"] is None
    payload["markets"][0]["bookmaker"] = "A"
    payload["markets"][1]["bookmaker"] = "B"
    assert sg.freeze(card,row,payload,{},.6,NOW) is None


def test_no_mutation_and_rolling_comparison(monkeypatch):
    card,row,payload = inputs()
    encoded = json.dumps(row).encode()
    monkeypatch.delenv("BLINQ_POINT_SG_SHADOW",raising=False)
    assert not sg.enabled()
    sg.freeze(card,row,payload,{},.6,NOW)
    assert json.dumps(row).encode() == encoded
    record = {"level":"ATP","scheduled":START,"markets":"[]",
              "sg_results":json.dumps([["games","point","push",0],["games","current","loss",-1]])}
    assert "sg_comparison" not in summarize([record])
    monkeypatch.setenv("BLINQ_POINT_SG_SHADOW","true")
    grouped = summarize([record])["sg_comparison"]
    point = next(r for r in grouped if (r["model"],r["level"],r["market"])==("point","ATP","games"))
    assert point["push"]==1 and point["yield"]==0 and point["hit"] is None
    assert point["per_day"]==pytest.approx(1/90)
