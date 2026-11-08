"""Most Aces quote research must never interpret player-total as a bet."""
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import probe_viac_es_real_odds as probe

NOW = datetime(2026,11,8,7,30,tzinfo=timezone.utc)
STAMP = "2026-11-08T13:30:00+00:00"

def fixture(event="9876"):
    return {"event_id":event,"market":"aces","scheduled_at":STAMP,"tour":"ATP",
            "player1":{"id":"11","name":"Ana A"},
            "player2":{"id":"22","name":"Bob B"},
            "aces_superiority_hint":"Ana A","aces_superiority_player_id":"11",
            "selection_id":"22","price_contract":"player_total_ou",
            "market_line":5.5,"ou_side":"over","odds":1.70,
            "projection_confidence":0.72}

def payload(name="Most Aces",one=1.78,two=2.10,third=False):
    rows=[{"marketName":name,"choiceName":"Ana A","decimalOdds":one},
          {"marketName":name,"choiceName":"Bob B","decimalOdds":two}]
    if third:
        rows.append({"marketName":name,"choiceName":"Draw","decimalOdds":7.0})
    return {"markets":rows}

def snap(rows=None):
    return {"confirmed_only":True,"betting_day":"2026-11-08",
            "generated_at":"2026-11-08T06:30:00+00:00",
            "ace_picks":[fixture()] if rows is None else rows}

def site():
    return {"schema":1,"ok":True,"ready":True,"stale":False,
            "betting_day":"2026-11-08","generated_at":"2026-11-08T06:30:00+00:00",
            "visible_counts":{"ace_picks":3}}


def test_only_exact_two_player_most_aces():
    quote,diag=probe.exact_aces_quote(payload(),"Ana A","Bob B")
    assert quote["player1_odds"] == 1.78
    assert quote["player2_odds"] == 2.10
    assert diag["validated_two_way_markets"] == 1


@pytest.mark.parametrize("name",[
    "Ana A Aces Over/Under","Player Aces Total",
    "Match Winner","Most Aces First Set",
    "Total Aces","Aces Handicap",
])
def test_no_cross_market_odds(name):
    assert probe.exact_aces_quote(payload(name),"Ana A","Bob B")[0] is None


def test_dont_convert_three_way_draw_or_one_sided_to_two_way():
    assert probe.exact_aces_quote(payload(third=True),"Ana A","Bob B")[0] is None
    assert probe.exact_aces_quote({"markets":payload()["markets"][:1]},"Ana A","Bob B")[0] is None


def test_dont_mix_two_books_or_conflicting_outcomes():
    market=payload()
    market["markets"].append({"marketName":"Most Aces",
                              "choiceName":"Ana A","decimalOdds":1.82})
    assert probe.exact_aces_quote(market,"Ana A","Bob B")[0] is None


def test_ball_player_not_ou_selection():
    class Rapid:
        request_count=0
        rate_limit_remaining=12300
        def event_odds(self,event,provider_id=1):
            self.request_count+=1
            assert str(event)=="9876" and provider_id==1
            return payload()
    report=probe.audit(snap(),site(),NOW,rapid=Rapid(),prop=None)
    assert report["events_probed"] == 1 and report["priced_exact"] == 1
    assert report["rows"][0]["ball_player"]=="Ana A"
    assert report["rows"][0]["ball_player_id"]=="11"
    assert report["rows"][0]["quote"]==1.78
    assert report["rows"][0]["provider"]=="tennisapi1"
    assert report["rows"][0]["price_contract"]=="most_aces_two_way"
    assert report["cdb_writes"]==0 and report["tg_messages_sent"]==0
    assert "market_line" not in report["rows"][0]


def test_unpriced_does_not_copy_existing_ou_price():
    class Rapid:
        request_count=0
        rate_limit_remaining=8000
        def event_odds(self,event,provider_id=1):
            self.request_count+=1
            return payload("Ana A Aces Over/Under")
    report=probe.audit(snap(),site(),NOW,rapid=Rapid(),prop=None)
    assert report["unpriced"] == 1
    assert report["rows"][0]["quote"] is None
    assert report["rows"][0]["provider"] is None


def test_propline_bookkeeper_independent_and_tie_rejected():
    raw={"bookmakers":[{"key":"book-x","markets":[
        {"key":"most_aces","outcomes":[
            {"name":"Ana A","price":-125},{"name":"Bob B","price":115}]}]}]}
    quote=probe.prop_aces_quote(raw,("Ana A","Bob B"),"most_aces")
    assert quote is not None
    assert quote["bookmaker"]=="book-x"
    assert quote["player1_odds"] == 1.8
    raw["bookmakers"][0]["markets"][0]["outcomes"].append({"name":"Draw","price":650})
    assert probe.prop_aces_quote(raw,("Ana A","Bob B"),"most_aces") is None


def test_propline_not_used_when_api_pro_has_2way_price():
    class Rapid:
        request_count=0
        rate_limit_remaining=7000
        def event_odds(self,*args,**kwargs):
            self.request_count+=1
            return payload()
    class Prop:
        calls=0
        max_calls=7
        def get(self,*args,**kwargs):
            raise AssertionError("Fallback must not run when API Pro has exact Most Aces quote")
    out=probe.audit(snap(),site(),NOW,rapid=Rapid(),prop=Prop())
    assert out["priced_exact"]==1
    assert out["provider_requests"]["propline"]==0


def test_propline_fallback_requires_exact_match_and_advertised_market():
    class Rapid:
        request_count=0
        rate_limit_remaining=7000
        def event_odds(self,*args,**kwargs):
            self.request_count+=1
            return {"markets":[]}
    class Prop:
        calls=0
        max_calls=7
        remaining=900
        def get(self,path,params=None):
            self.calls+=1
            if path=="/sports/tennis/events":
                return {"events":[{"id":"12345","commence_time":STAMP,
                        "home_team":"Ana A","away_team":"Bob B"}]}
            if path.endswith("/markets"):return {"markets":[{"key":"player_aces"},{"key":"h2h"}]}
            raise AssertionError("Do not fetch O/U odds for Most Aces")
    out=probe.audit(snap(),site(),NOW,rapid=Rapid(),prop=Prop())
    assert out["priced_exact"]==0
    assert out["provider_requests"]["propline"]==2
    assert out["rows"][0]["propline"]=="no_advertised_most_aces_market"


def test_stale_website_rejected_before_any_api_request():
    class Rapid:
        request_count=0
        def event_odds(self,*args,**kwargs):
            raise AssertionError("No call before same-generation read-back")
    with pytest.raises(ValueError):
        probe.audit(snap(),{**site(),"generated_at":"2026-11-08T05:20:00+00:00"},
                    NOW,rapid=Rapid(),prop=None)


def test_no_ball_no_paid_requests():
    class Rapid:
        request_count=0
        def event_odds(self,*args,**kwargs):
            raise AssertionError("No ball on site")
    out=probe.audit(snap([]),site(),NOW,rapid=Rapid(),prop=None)
    assert out["status"]=="no_future_ball_marked_fixtures"
    assert out["provider_requests"]=={"api_pro":0,"propline":0}


def test_one_day_workflow_budget_and_storage_guards():
    wf=(Path(__file__).resolve().parents[1]/
        ".github/workflows/viac-es-odds-probe.yml").read_text()
    assert "2026-11-08" in wf
    assert "BLINQ_SHARED_API_BUDGET_URL" in wf
    assert "BLINQ_PROVIDER_REQUEST_RESERVE: '500'" in wf
    assert "max-events 3" in wf
    assert "telegram-bot-state" in wf
    assert "BlinQ Telegram complete daily offer (06:20 queue)" in wf
    assert "cdb_writes" in wf and "tg_messages_sent" in wf
