from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from tbt.services.engine import reconcile_ledger, serving_feed
from tbt.services.market_selection import annotate_market_publication_candidates, select_market_sections
from tbt.services.publication import (
    confirm_market_publications,
    reconcile_market_feed_with_ledger,
    validate_market_publication_candidate,
)


def _market_row(event_id='evt', probability=.80, odds=1.90, implied=.56):
    return {
        'id': f'm-{event_id}',
        'event_id': event_id,
        'scheduled_at': '2026-09-07T15:00:00+00:00',
        'tour': 'ATP',
        'tournament': 'Test Open',
        'surface': 'hard',
        'round': 'R16',
        'competition': 'ATP',
        'player1': {'id': 'A', 'name': 'Alpha', 'probability': probability},
        'player2': {'id': 'B', 'name': 'Beta', 'probability': 1-probability},
        'winner_id': 'A',
        'confidence': probability,
        'data_depth': .8,
        'quality': {
            'player1': {'matches': 50, 'surface_matches': 20},
            'player2': {'matches': 50, 'surface_matches': 20},
            'surface_known': True,
        },
        'signals': [],
        'model_version': 'test',
        'created_at': '2026-09-07T08:00:00+00:00',
        'issued_at': '2026-09-07T08:05:00+00:00',
        'publication_status': 'published',
        'result': None,
        'betting': {
            'market': 'match_winner',
            'selection': 'Alpha',
            'selection_id': 'A',
            'odds': odds,
            'fair_implied_probability': implied,
            'model_probability': probability,
            'edge': probability-implied,
            'expected_value': probability*odds-1,
            'provider_id': 1,
            'captured_at': '2026-09-07T08:00:00+00:00',
            'betting_day': '2026-09-07',
        },
        'match_winner_market': {
            'player1_implied_probability': .55,
            'player2_implied_probability': .45,
        },
    }


def test_market_section_publication_is_confirmed_only_from_matching_deployed_feed():
    annotated = annotate_market_publication_candidates([_market_row()])
    candidate = annotated[0]
    ledger = [{**candidate, 'market_publications': candidate['market_publication_candidates']}]
    ledger[0].pop('market_publication_candidates', None)
    sections = select_market_sections(annotated)
    feed = {
        'top_daily_picks': sections['top_daily_picks'],
        'prime_picks': sections['prime_picks'],
        'value_picks': sections['value_picks'],
        'market_selection': {'publication_schema': 1},
    }
    assert validate_market_publication_candidate(feed, ledger) == 1
    confirmed, count = confirm_market_publications(
        ledger,
        feed,
        datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc),
    )
    assert count == 1
    assert all(p['issued_at'] for p in confirmed[0]['market_publications'])
    assert all(p['publication_status'] == 'published' for p in confirmed[0]['market_publications'])


def test_settled_market_publications_produce_real_flat_unit_roi(match_factory):
    row = _market_row()
    annotated = annotate_market_publication_candidates([row])[0]
    publications = annotated['market_publication_candidates']
    # v6 assigns an underlying Match Winner selection to exactly one public
    # offer, so no cross-section ROI deduplication is needed for new picks.
    for publication in publications:
        publication['issued_at'] = '2026-09-07T09:00:00+00:00'
        publication['publication_status'] = 'published'
    ledger = [{**row, 'market_publications': publications}]

    completed = match_factory('completed', 'A', 'B', 'A', day=7)
    completed.provider_payload = {'id': 'evt'}
    completed.scheduled_at = datetime(2026, 9, 7, 15, 0, tzinfo=timezone.utc)
    settled = reconcile_ledger(
        ledger,
        [],
        [completed],
        datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc),
    )
    assert all(p['result']['correct'] is True for p in settled[0]['market_publications'])
    assert all(abs(p['result']['profit_units'] - .90) < 1e-12 for p in settled[0]['market_publications'])

    feed = serving_feed(
        settled,
        SimpleNamespace(version='test'),
        [completed],
        {},
        [],
        datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc),
    )
    overall = feed['betting_performance']['overall']
    assert overall['n'] == 1
    assert overall['wins'] == 1
    assert abs(overall['roi'] - .90) < 1e-12
    assert feed['betting_performance']['sections']['top_daily']['n'] == 1
    assert feed['betting_performance']['sections']['prime']['n'] == 0
    assert feed['betting_performance']['sections']['value']['n'] == 0
    assert feed['results_meta']['settled_total'] == 1



def test_refresh_restores_already_issued_market_snapshot_instead_of_republishing_new_odds():
    original = annotate_market_publication_candidates([_market_row(odds=1.90)])[0]
    publications = [dict(item) for item in original['market_publication_candidates']]
    assert len(publications) == 1
    publications[0]['issued_at'] = '2026-09-07T09:00:00+00:00'
    publications[0]['publication_status'] = 'published'
    ledger_row = {**original, 'market_publications': publications}
    ledger_row.pop('market_publication_candidates', None)
    ledger = [ledger_row]

    refreshed = _market_row(odds=1.84)
    sections = select_market_sections([refreshed])
    feed = {
        'top_daily_picks': sections['top_daily_picks'],
        'prime_picks': sections['prime_picks'],
        'value_picks': sections['value_picks'],
        'market_selection': {'publication_schema': 1},
    }

    # Moving provider odds for the same already-issued offer are intentionally
    # rejected until the serving row is restored to the audited snapshot.
    try:
        validate_market_publication_candidate(feed, ledger)
    except RuntimeError:
        pass
    else:
        raise AssertionError('refreshed untracked odds unexpectedly validated')

    assert reconcile_market_feed_with_ledger(feed, ledger) == 1
    assert validate_market_publication_candidate(feed, ledger) == 1
    row = feed['top_daily_picks'][0]
    assert row['odds'] == 1.90
    assert row['betting']['odds'] == 1.90
    assert row['probability'] == publications[0]['model_probability']
    assert row['winner_id'] == ledger_row['winner_id']
    assert feed['market_selection']['restored_issued_snapshots'] == 1


def test_refresh_does_not_rewrite_unrelated_or_new_market_offer():
    original = annotate_market_publication_candidates([_market_row(event_id='old', odds=1.90)])[0]
    publications = [dict(item) for item in original['market_publication_candidates']]
    publications[0]['issued_at'] = '2026-09-07T09:00:00+00:00'
    publications[0]['publication_status'] = 'published'
    ledger_row = {**original, 'market_publications': publications}
    ledger_row.pop('market_publication_candidates', None)

    fresh = _market_row(event_id='new', odds=1.84)
    sections = select_market_sections([fresh])
    feed = {
        'top_daily_picks': sections['top_daily_picks'],
        'prime_picks': sections['prime_picks'],
        'value_picks': sections['value_picks'],
        'market_selection': {'publication_schema': 1},
    }
    assert reconcile_market_feed_with_ledger(feed, [ledger_row]) == 0
    assert feed['top_daily_picks'][0]['odds'] == 1.84
