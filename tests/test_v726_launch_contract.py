from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_top_dynamic_fallback_contract_present():
    src=(ROOT/'api/tbt/services/market_selection.py').read_text()
    assert 'TOP_DYNAMIC_FALLBACK_MIN_PROBABILITY = 0.65' in src
    assert 'TOP_FALLBACK_MIN_ODDS = 1.50' in src
    assert 'TOP_MIN_COUNT = 5' in src
    assert '(0.65, 1.50)' in src


def test_info_general_audience_and_live_minimum_is_dynamic(monkeypatch):
    from tbt.services import admin_storage
    monkeypatch.setattr(admin_storage, 'load_runtime_ui_config', lambda: {'notifications': {'live_min_level': 'legend'}})
    info=admin_storage.normalize_insight({'title':'Info','body':'Body','type':'vip','levels':['rookie','pro','elite','legend','goat']})
    assert info['levels'][0]=='rookie'
    live=admin_storage.normalize_insight({'title':'Live','body':'Body','type':'set2','levels':['legend','goat']})
    assert live['levels']==['legend','goat']
    try:
        admin_storage.normalize_insight({'title':'Live','body':'Body','type':'set2','levels':['elite']})
    except ValueError as exc:
        assert 'LEGEND' in str(exc)
    else:
        raise AssertionError('Set2 LIVE must respect the published LIVE minimum')


def test_set2_push_requires_real_market_positive_value_and_depth():
    from tbt.services.live_comeback import set2_push_eligible
    base={
        'second_set_probability':.68,
        'second_set_quality':'medium',
        'second_set_samples':14,
        'second_set_odds':1.70,
        'second_set_edge':.08,
        'second_set_ev':.156,
    }
    assert set2_push_eligible(base)
    assert not set2_push_eligible({**base,'second_set_odds':None})
    assert not set2_push_eligible({**base,'second_set_edge':-.01})
    assert not set2_push_eligible({**base,'second_set_quality':'low'})
    assert not set2_push_eligible({**base,'second_set_samples':4})


def test_esa_cards_are_explicit_player_projections():
    src=(ROOT/'api/tbt/services/ace_selection.py').read_text()
    assert '"projection_scope": "player"' in src
    assert '"projection_kind": "player_aces" if market == "aces" else "player_double_faults"' in src
    app=(ROOT/'web/app.js').read_text()
    assert 'aceProjectionTypeLabel' in app
    assert "lcopy('PLAYER','HRÁČ','HRÁČ')" in app


def test_esa_projection_publications_are_frozen_and_settled_without_roi(match_factory):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from tbt.services.engine import reconcile_ledger, serving_feed
    from tbt.services.market_selection import annotate_market_publication_candidates
    from tbt.services.publication import confirm_market_publications, validate_market_publication_candidate

    base={
        'id':'m-evt-esa','event_id':'evt-esa','scheduled_at':'2026-09-18T15:00:00+00:00',
        'tour':'ATP','tournament':'Test Open','surface':'hard','competition':'ATP',
        'player1':{'id':'A','name':'Alpha','probability':.70},
        'player2':{'id':'B','name':'Beta','probability':.30},
        'winner_id':'A','confidence':.70,'data_depth':.82,
        'quality':{'player1':{'matches':30,'surface_matches':12},'player2':{'matches':30,'surface_matches':12},'surface_known':True},
        'signals':[],'model_version':'test','created_at':'2026-09-18T08:00:00+00:00',
        'betting':None,
    }
    ace={
        **base,'market':'aces','market_type':'Most Aces','projection_scope':'player',
        'projection_metric':'aces','projection_kind':'player_aces','projection_subject':'Alpha',
        'projection_label':'Hráč · Esá','pick':'Alpha','selection':'Alpha','selection_id':'A',
        'projection':7.2,'opponent_projection':4.1,'projection_gap':3.1,'projection_confidence':.84,
        'projection_samples':{'player1':18,'player2':16,'player1_surface':8,'player2_surface':7},
        'price_status':'projection_only','odds':None,'edge':None,'expected_value':None,
    }
    annotated=annotate_market_publication_candidates([base],ace_picks=[ace])[0]
    ledger=[{**annotated,'market_publications':annotated['market_publication_candidates']}]
    ledger[0].pop('market_publication_candidates',None)
    feed={'top_daily_picks':[],'prime_picks':[],'value_picks':[],'ace_picks':[ace], 'market_selection':{'publication_schema':1}}
    assert validate_market_publication_candidate(feed,ledger)==1
    ledger,count=confirm_market_publications(ledger,feed,datetime(2026,9,18,9,0,tzinfo=timezone.utc))
    assert count==1
    pub=ledger[0]['market_publications'][0]
    assert pub['projection_label']=='Hráč · Esá' and pub['price_status']=='projection_only'

    completed=match_factory('completed','A','B','A',day=18)
    completed.provider_payload={'id':'evt-esa'}
    completed.scheduled_at=datetime(2026,9,18,15,0,tzinfo=timezone.utc)
    completed.stats={'p1_aces':9,'p2_aces':5,'p1_double_faults':2,'p2_double_faults':3}
    # The base prediction itself must have been public pre-match for its result row
    # to enter the serving results feed; market publications retain their own issue time.
    ledger[0]['issued_at']='2026-09-18T09:00:00+00:00'
    ledger[0]['publication_status']='published'
    settled=reconcile_ledger(ledger,[],[completed],datetime(2026,9,18,18,0,tzinfo=timezone.utc))
    result=settled[0]['market_publications'][0]['result']
    assert result['status']=='hit' and result['correct'] is True
    assert result['actual_count']==9 and result['opponent_actual_count']==5
    assert 'profit_units' not in result and 'staked_units' not in result
    out=serving_feed(settled,SimpleNamespace(version='test'),[completed],{},[],datetime(2026,9,18,18,0,tzinfo=timezone.utc))
    assert out['betting_performance']['overall']['n']==0
    assert out['betting_performance']['projections']['aces']['n']==1
    assert out['betting_performance']['projections']['aces']['hit_rate']==1.0


def test_results_ui_calls_esa_a_projection_not_prediction():
    app=(ROOT/'web/app.js').read_text()
    assert 'projectionResultTypeLabel' in app
    assert 'Projekcia pre' in app
    assert 'DATA DEPTH' in app
    assert '✓ HIT' in app and '× MISS' in app
    assert 'MODEL 2. SETU · samostatný podporný signál' in app


def test_info_minimum_is_dynamic_and_cannot_be_widened(monkeypatch):
    from tbt.services import admin_storage
    monkeypatch.setattr(admin_storage, 'load_runtime_ui_config', lambda: {'notifications': {'info_min_level': 'pro', 'live_min_level': 'elite'}})
    info=admin_storage.normalize_insight({'title':'Info','body':'Body','type':'vip','levels':['pro','elite','legend','goat']})
    assert info['levels'][0]=='pro'
    try:
        admin_storage.normalize_insight({'title':'Info','body':'Body','type':'vip','levels':['rookie']})
    except ValueError as exc:
        assert 'PRO' in str(exc)
    else:
        raise AssertionError('INFO must respect the published INFO minimum')
