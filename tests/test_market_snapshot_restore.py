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
