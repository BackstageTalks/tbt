from datetime import datetime, timezone
from tbt.services.live_comeback import evaluate_prime_live, scan_comeback_radar, settle_radar_results
from tbt.services.entitlements import filter_feed_for_access

def prime_row(event_id='123', probability=.88, odds=1.18):
    return {'event_id':event_id,'scheduled_at':datetime.now(timezone.utc).isoformat(),'player1':{'id':'10','name':'Favorite','probability':probability},'player2':{'id':'20','name':'Opponent','probability':1-probability},'betting':{'selection_id':'10','selection':'Favorite','odds':odds,'blinq_probability':probability},'odds':odds,'probability':probability}
def live_event(first=(4,6),second=(3,1),status='inprogress'):
    return {'id':'123','status':{'type':status},'homeTeam':{'id':'10','name':'Favorite'},'awayTeam':{'id':'20','name':'Opponent'},'homeScore':{'period1':first[0],'period2':second[0]},'awayScore':{'period1':first[1],'period2':second[1]},'tournament':{'name':'Test Open'}}
def test_waits_until_second_set_has_real_lead():
    c=evaluate_prime_live(prime_row(),live_event(second=(2,1)),min_probability=.78,max_odds=1.35);assert c and not c.trigger
def test_triggers_on_break_lead():
    c=evaluate_prime_live(prime_row(),live_event(second=(3,1)),min_probability=.78,max_odds=1.35);assert c and c.trigger and c.stage=='break_lead'
def test_triggers_after_second_set_win():
    c=evaluate_prime_live(prime_row(),live_event(second=(6,3)),min_probability=.78,max_odds=1.35);assert c and c.trigger and c.stage=='second_set_won'
def test_rejects_weak_high_odds_or_first_set_winner():
    assert evaluate_prime_live(prime_row(),live_event(first=(6,4)),min_probability=.78,max_odds=1.35) is None
    assert evaluate_prime_live(prime_row(probability=.70),live_event(),min_probability=.78,max_odds=1.35) is None
    assert evaluate_prime_live(prime_row(odds=1.55),live_event(),min_probability=.78,max_odds=1.35) is None
def test_scan_and_short_odds_can_share_prime_pool(monkeypatch):
    monkeypatch.setenv('BLINQ_LIVE_RADAR_MIN_PROBABILITY','0.78');monkeypatch.setenv('BLINQ_LIVE_RADAR_MAX_ODDS','1.35')
    scan=scan_comeback_radar({'prime_picks':[prime_row()]},[live_event()]);assert len(scan['signals'])==1
    payload={'prime_picks':[prime_row()],'top_daily_picks':[],'value_picks':[],'ace_picks':[],'sg_picks':[],'doubles_picks':[],'upcoming':[],'results':[]}
    public,manifest=filter_feed_for_access(payload,{'status':'active','plan':'elite'});assert len(public['prime_picks'])==1 and manifest['sections']['prime']['enabled'] is True


def test_watch_stage_exists_before_confirmed_signal():
    scan=scan_comeback_radar({'prime_picks':[prime_row()]},[live_event(second=(2,1))])
    assert len(scan['candidates'])==1
    assert scan['candidates'][0]['stage']=='watch'
    assert scan['signals']==[]


def test_results_only_settle_previously_published_confirmed_signals(monkeypatch):
    from tbt.services import live_comeback as live
    saved = []
    sources = {
        "live-comeback-123": {
            "id": "live-comeback-123", "title": "Comeback LIVE · Favorite",
            "created_at": "2026-09-25T10:00:00+00:00",
        },
        "live-set2-123": {
            "id": "live-set2-123", "title": "2. set LIVE · Favorite",
            "created_at": "2026-09-25T10:01:00+00:00",
        },
    }
    monkeypatch.setattr(live, "load_insight_by_id", lambda insight_id: sources.get(insight_id))
    monkeypatch.setattr(live, "save_live_radar_result", lambda payload, result_id: saved.append((result_id, payload)) or payload)

    out = settle_radar_results([{
        "event_id": "123", "match_status": "win", "second_set_status": "loss",
        "checked_at": "2026-09-25T12:00:00+00:00",
    }])

    assert out == {"saved": 2, "comeback": 1, "set2": 1}
    assert saved[0][0] == "live-result-comeback-123"
    assert saved[0][1]["outcome"] == "win"
    assert saved[1][0] == "live-result-set2-123"
    assert saved[1][1]["outcome"] == "loss"


def test_watch_only_candidate_never_enters_results(monkeypatch):
    from tbt.services import live_comeback as live
    saved = []
    monkeypatch.setattr(live, "load_insight_by_id", lambda _insight_id: None)
    monkeypatch.setattr(live, "save_live_radar_result", lambda payload, result_id: saved.append((result_id, payload)))
    out = settle_radar_results([{
        "event_id": "123", "match_status": "win", "second_set_status": "win",
        "checked_at": "2026-09-25T12:00:00+00:00",
    }])
    assert out["saved"] == 0
    assert saved == []


def test_confirmed_retirement_is_void_with_separate_public_skrec_reason(monkeypatch):
    from tbt.services import live_comeback as live
    saved = []
    monkeypatch.setattr(live, "load_insight_by_id", lambda insight_id:
                        {"id": insight_id, "title": "Comeback LIVE"} if insight_id == "live-comeback-123" else None)
    monkeypatch.setattr(live, "save_live_radar_result",
                        lambda payload, result_id: saved.append(payload))
    out = settle_radar_results([{
        "event_id": "123", "match_status": "retired",
        "second_set_status": "",
    }])
    assert out["comeback"] == 1
    assert saved[0]["outcome"] == "void"
    assert saved[0]["reason"] == "retired"
