from datetime import datetime, timezone
from tbt.services.live_comeback import evaluate_prime_live, scan_comeback_radar
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
def test_scan_and_prime_never_public(monkeypatch):
    monkeypatch.setenv('BLINQ_LIVE_RADAR_MIN_PROBABILITY','0.78');monkeypatch.setenv('BLINQ_LIVE_RADAR_MAX_ODDS','1.35')
    scan=scan_comeback_radar({'prime_picks':[prime_row()]},[live_event()]);assert len(scan['signals'])==1
    payload={'prime_picks':[prime_row()],'top_daily_picks':[],'value_picks':[],'ace_picks':[],'sg_picks':[],'doubles_picks':[],'upcoming':[],'results':[]}
    public,manifest=filter_feed_for_access(payload,{'status':'active','plan':'elite'});assert public['prime_picks']==[] and manifest['sections']['prime']['internal_only'] is True


def test_watch_stage_exists_before_confirmed_signal():
    scan=scan_comeback_radar({'prime_picks':[prime_row()]},[live_event(second=(2,1))])
    assert len(scan['candidates'])==1
    assert scan['candidates'][0]['stage']=='watch'
    assert scan['signals']==[]
