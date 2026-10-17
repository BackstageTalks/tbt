"""Regression contracts for a frozen all-candidate replay."""
import pytest
pytest.importorskip('backtest_archived_candidates')
from backtest_archived_candidates import read_candidates,rank,evaluate

def source(day='2026-10-11',count=7):
    snap={'generated_at':day+'T06:00:00+00:00','rows':[]}
    ledger=[]
    for i in range(count):
        event='evt'+str(i)
        snap['rows'].append({'event_id':event,'winner_id':'p1',
            'scheduled_at':day+'T16:00:00+00:00',
            'raw_model_probability':.72+i*.01, 'blinq_probability':.7+i*.01,
            'data_depth':.9,'selected_section':'top_daily' if i==1 else None,
            'player1':{'id':'p1'},'player2':{'id':'p2'},
            'betting':{'selection_id':'p1','captured_at':day+'T05:00:00+00:00','odds':1.7},
            'two_way_market':{'captured_at':day+'T05:00:00+00:00','player1_odds':1.7,'player2_odds':2.2}})
        ledger.append({'event_id':event,'result':{'winner_id':'p1' if i%2==0 else 'p2',
            'settled_at':day+'T19:00:00+00:00'}})
    return {'snapshots':[snap]},ledger

def test_caps_and_original_cohort():
    s,l=source(); rows,days,diag=read_candidates(s,l)
    assert len(rows)==7 and days==['2026-10-11']
    assert len(rank(rows,'top_daily','raw_model',3,days))==3
    assert len(rank(rows,'top_daily','raw_model',5,days))==5
    assert len(rank(rows,'top_daily','original',5,days))==1
    assert rank(rows,'top_daily','original',5,days)[0]['event_id']=='evt1'

def test_late_quote_and_same_day_clock_are_excluded():
    s,l=source(); s['snapshots'][0]['rows'][0]['betting']['captured_at']='2026-10-11T07:00:00+00:00'
    s['snapshots'][0]['rows'][1]['scheduled_at']='2026-10-11T05:59:59+00:00'
    rows,days,d=read_candidates(s,l)
    assert len(rows)==5
    assert d['quote_missing_or_post_snapshot']==1
    assert d['invalid_or_started_before_snapshot']==1

def test_outcome_does_not_change_rank_and_pending_is_retained():
    s,l=source()
    rows,days,_=read_candidates(s,l)
    ids=[r['event_id'] for r in rank(rows,'top_daily','raw_model',3,days)]
    for row in l:row['result']={}
    rows2,_,_=read_candidates(s,l)
    assert [r['event_id'] for r in rank(rows2,'top_daily','raw_model',3,days)]==ids
    assert all(r['outcome']=='pending' for r in rows2)

def test_event_identity_combined_is_not_double_staked():
    s,l=source()
    rows,days,_=read_candidates(s,l)
    result=evaluate(rows,days)
    assert result['policies']['combined|TOP_raw_then_VALUE_EV|n3']['all']['issued_selected']<=3


def test_snapshot_after_noon_valid_and_before_six_previous_day():
    s,l=source()
    s['snapshots'][0]['generated_at']='2026-10-11T13:00:00+00:00'
    rows,days,diag=read_candidates(s,l)
    assert len(rows)==7 and days==['2026-10-11']
    s['snapshots'][0]['generated_at']='2026-10-11T03:00:00+00:00'
    for r in s['snapshots'][0]['rows']:
        r['betting']['captured_at']='2026-10-11T02:00:00+00:00'
        r['two_way_market']['captured_at']='2026-10-11T02:00:00+00:00'
    rows,days,diag=read_candidates(s,l)
    assert len(rows)==7 and days==['2026-10-10']
