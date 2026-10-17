import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from datetime import datetime,timezone
from backtest_top_value_pit import normalize, choose,run,summarize,cutoff,day,prob


def make(event, section='top_daily', at='2026-10-11T08:00:00+00:00', price=1.7, result=True, model=.72):
    return {'event_id':event,'scheduled_at':'2026-10-11T17:00:00+00:00',
      'market_publications':[{'section':section,'market':'match_winner','selection_id':'p1',
      'odds':price,'issued_at':at,'captured_at':'2026-10-11T07:00:00+00:00',
      'model_probability':model,'result':{'correct':result}}]}


def verified(pub):
    return {'model_probability':pub.get('model_probability'),'blinq_probability':.74,
            'market_captured_at':'2026-10-11T07:00:00+00:00',
            'two_way_match_winner':{'player1_odds':1.7,'player2_odds':2.2},
            'players':{'player1':{'id':'p1'},'player2':{'id':'p2'}},
            'quality':{'player1':{'surface_matches':12},'player2':{'surface_matches':8}},
            'data_depth':.92}

def test_no_future_issuance_or_outcome_selection():
    a=make('a');b=make('b',at='2026-10-11T14:00:00+00:00',result=False)
    rows,_=normalize([a,b],verified)
    chosen=choose(rows,'model',5,'top_daily')
    assert len(chosen)==1 and chosen[0]['event_id']=='a'
    rows[0]['outcome']='pending'
    assert len(choose(rows,'model',5,'top_daily'))==1

def test_declared_threshold_and_daily_cap():
    ledger=[make(str(i),price=1.7,model=.75+i*.01) for i in range(10)]
    ledger.append(make('below',price=1.49))
    rows,_=normalize(ledger,verified)
    assert len(rows)==10
    assert [r['event_id'] for r in choose(rows,'model',3,'top_daily')]==['9','8','7']

def test_two_categories_and_overlapping_selection():
    a=make('a');a['market_publications']+= [{**a['market_publications'][0], 'section':'value'}]
    report,rows=run([a],{},[],{},verified)
    assert len(rows)==2
    assert report['categories']['top_daily']['original_all_issued']['issued_selected']==1
    assert report['categories']['value']['original_all_issued']['issued_selected']==1
    assert report['comparisons']['combined|TOP_model_then_VALUE_EV|n3']['full']['issued_selected']==1

def test_unresolved_stays_in_denominator():
    a=make('a');a['market_publications'][0]['result']={}
    rows,_=normalize([a],verified)
    report=summarize(rows,['2026-10-11'])
    assert report['issued_selected']==1 and report['settled']==0 and report['unsettled']==1

def test_duplicate_conflict_not_selection_filtered():
    a=make('a');b=make('a',result=False)
    r,count=normalize([a,b],verified)
    assert len(r)==1 and r[0]['outcome']=='pending' and count['conflicting_duplicate_rows']==1
    assert len(choose(r,'model',3,'top_daily'))==1

def test_prob_and_market_no_vig():
    assert prob(74)==.74
    a=make('a')
    r,_=normalize([a],verified)
    p=r[0]['fair_market_probability']
    assert p is not None and abs(p-((1/1.7)/(1/1.7+1/2.2)))<1e-10
