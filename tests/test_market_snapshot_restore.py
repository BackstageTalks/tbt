from copy import deepcopy
import pytest
from tbt.services.publication import restore_published_market_snapshots, validate_market_publication_candidate


def artifacts():
    betting = dict(market='match_winner', selection_id='A', selection='Alpha', odds=1.36,
                   model_probability=.71278, edge=.02528, expected_value=-.028,
                   betting_day='2026-09-09')
    row = dict(event_id='16983980', betting=betting, probability=.71278,
               player1=dict(id='A', probability=.71278), player2=dict(id='B', probability=.28722))
    publication = dict(betting, section='top_daily', model_probability=.71281,
                       edge=.02531, expected_value=-.02799, issued_at='2026-09-09T17:00:00Z',
                       publication_status='published')
    return {'top_daily_picks':[row]}, [{'event_id':'16983980','market_publications':[publication]}]


def test_restore_issued_snapshot_without_mutating_inputs():
    feed, ledger = artifacts()
    originals = deepcopy((feed, ledger))
    with pytest.raises(RuntimeError):
        validate_market_publication_candidate(feed, ledger)
    restored = restore_published_market_snapshots(feed, ledger)
    assert validate_market_publication_candidate(restored, ledger) == 1
    row = restored['top_daily_picks'][0]
    assert row['betting']['model_probability'] == row['probability'] == row['player1']['probability'] == .71281
    assert (feed, ledger) == originals
    assert restore_published_market_snapshots(restored, ledger) == restored


@pytest.mark.parametrize('field,value', [('selection_id','B'),('betting_day','2026-09-10'),('section','value'),('market','total_games'),('issued_at',None),('publication_status','pending')])
def test_never_repair_different_identity_or_pending(field, value):
    feed, ledger = artifacts()
    ledger[0]['market_publications'][0][field] = value
    with pytest.raises(RuntimeError):
        restore_published_market_snapshots(feed, ledger)


def test_reject_ambiguous_or_missing_ledger():
    feed, ledger = artifacts()
    ledger[0]['market_publications'] *= 2
    with pytest.raises(RuntimeError):
        restore_published_market_snapshots(feed, ledger)
    with pytest.raises(RuntimeError):
        restore_published_market_snapshots(feed, [])


def test_preserve_exact_pending_snapshot():
    feed, ledger = artifacts()
    publication=ledger[0]['market_publications'][0]
    publication.update(feed['top_daily_picks'][0]['betting'], issued_at=None, publication_status='pending')
    assert restore_published_market_snapshots(feed, ledger) == feed


def _ace_artifacts(projection=7.2):
    row = {
        'event_id':'17125475', 'market':'aces', 'selection_id':'A', 'selection':'Alpha',
        'projection':projection, 'opponent_projection':4.0,
        'projection_scope':'player', 'projection_metric':'aces',
        'projection_confidence':.84, 'projection_label':'Hráč · Esá',
        'price_status':'projection_only',
    }
    publication = {
        'section':'ace','market':'aces','selection_id':'A','selection':'Alpha',
        'odds':None,'model_probability':None,'edge':None,'expected_value':None,
        'betting_day':None,'projection':6.8,'opponent_projection':4.1,
        'projection_scope':'player','projection_metric':'aces',
        'projection_confidence':.82,'projection_label':'Hráč · Esá',
        'price_status':'projection_only','issued_at':'2026-09-18T10:00:00+00:00',
        'publication_status':'published',
    }
    return {'ace_picks':[row]}, [{'event_id':'17125475','market_publications':[publication]}]


def test_projection_restore_uses_unique_issued_snapshot():
    feed, ledger = _ace_artifacts()
    restored = restore_published_market_snapshots(feed, ledger)
    assert len(restored['ace_picks']) == 1
    assert restored['ace_picks'][0]['projection'] == 6.8
    assert validate_market_publication_candidate(restored, ledger) == 1


def test_projection_legacy_conflict_is_quarantined_not_deploy_blocking():
    feed, ledger = _ace_artifacts()
    conflicting = deepcopy(ledger[0]['market_publications'][0])
    conflicting.update(projection=8.1, issued_at='2026-09-18T11:00:00+00:00')
    ledger[0]['market_publications'].append(conflicting)
    restored = restore_published_market_snapshots(feed, ledger)
    assert restored['ace_picks'] == []
    assert validate_market_publication_candidate(restored, ledger) == 0


def test_projection_missing_ledger_is_quarantined_not_deploy_blocking():
    feed, _ = _ace_artifacts()
    restored = restore_published_market_snapshots(feed, [])
    assert restored['ace_picks'] == []


def test_projection_lifecycle_duplicates_with_identical_snapshot_are_safe():
    feed, ledger = _ace_artifacts()
    duplicate = deepcopy(ledger[0]['market_publications'][0])
    duplicate['issued_at'] = '2026-09-18T11:00:00+00:00'
    ledger[0]['market_publications'].append(duplicate)
    restored = restore_published_market_snapshots(feed, ledger)
    assert len(restored['ace_picks']) == 1
    assert restored['ace_picks'][0]['projection'] == 6.8


def test_sg_pending_snapshot_uses_match_total_identity_and_survives_restore():
    row = {
        'event_id':'sg-1','market':'games','selection_id':'games:high','selection':'High Total Games',
        'projection':24.7,'reference_projection':20.5,'projection_scope':'match_total',
        'projection_metric':'games','projection_confidence':.71,'projection_label':'Zápas · Gamy',
        'price_status':'projection_only',
    }
    publication = {
        'section':'games','market':'games','selection_id':'games:high','selection':'High Total Games',
        'odds':None,'model_probability':None,'edge':None,'expected_value':None,'betting_day':None,
        'projection':24.7,'opponent_projection':None,'projection_scope':'match_total','projection_metric':'games',
        'projection_confidence':.71,'projection_label':'Zápas · Gamy','price_status':'projection_only',
        'issued_at':None,'publication_status':'pending',
    }
    feed={'sg_picks':[row]}
    ledger=[{'event_id':'sg-1','market_publications':[publication]}]
    restored=restore_published_market_snapshots(feed,ledger)
    assert restored['sg_picks']==[row]
    assert validate_market_publication_candidate(restored,ledger)==1
