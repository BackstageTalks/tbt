import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from tbt.services.engine import reconcile_ledger, serving_feed
from tbt.services.market_selection import annotate_market_publication_candidates, select_market_sections
from tbt.services.publication import (
    confirm_market_publications,
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


def test_public_results_keep_all_actually_issued_history_without_artificial_reset():
    def settled_row(event_id, issued_at, scheduled_at):
        row = _market_row(event_id=event_id)
        row['issued_at'] = issued_at
        row['scheduled_at'] = scheduled_at
        row['result'] = {'winner_id': 'A', 'correct': True, 'settled_at': scheduled_at}
        row['market_publications'] = [{
            'schema': 1,
            'publication_key': f'top_daily:{event_id}',
            'selection_key': f'match_winner:{event_id}:A',
            'section': 'top_daily',
            'market': 'match_winner',
            'selection': 'Alpha',
            'selection_id': 'A',
            'odds': 1.9,
            'model_probability': .8,
            'issued_at': issued_at,
            'publication_status': 'published',
            'result': {
                'winner_id': 'A', 'correct': True, 'staked_units': 1.0,
                'return_units': 1.9, 'profit_units': .9,
                'settled_at': scheduled_at, 'scheduled_at': scheduled_at,
            },
        }]
        return row

    old = settled_row('old', '2026-09-18T08:00:00+00:00', '2026-09-18T15:00:00+00:00')
    new = settled_row('new', '2026-09-19T08:00:00+00:00', '2026-09-19T15:00:00+00:00')
    feed = serving_feed(
        [old, new], SimpleNamespace(version='test'), [], {}, [],
        datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc),
    )
    assert [row['event_id'] for row in feed['results']] == ['new', 'old']
    assert feed['results_meta']['history_reset'] is False
    assert feed['results_meta']['history_cutoff'] is None
    assert feed['results_meta']['history_policy'] == 'all_actually_issued_settled'
    assert feed['betting_performance']['overall']['n'] == 2


def test_sets_and_games_are_confirmed_and_settled_from_public_feed(match_factory):
    scheduled = datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)
    base = _market_row(event_id='sg-event')
    base['scheduled_at'] = scheduled.isoformat()
    base.pop('betting', None)
    base.pop('match_winner_market', None)
    base['issued_at'] = None
    base['publication_status'] = 'pending'

    sg_picks = [
        {
            **base,
            'market': 'sets', 'selection_id': 'sets:over:2.5',
            'selection': 'Over 2.5 Sets', 'pick': 'Over 2.5 Sets',
            'projection': .72, 'projection_confidence': .72,
            'projection_scope': 'match_total', 'projection_metric': 'sets',
            'reference_projection': 2.5, 'price_status': 'projection_only',
        },
        {
            **base,
            'market': 'games', 'selection_id': 'games:high',
            'selection': 'High Total Games', 'pick': 'High Total Games',
            'projection': 28.0, 'projection_confidence': .75,
            'projection_scope': 'match_total', 'projection_metric': 'games',
            'projection_direction': 'high', 'reference_projection': 24.0,
            'price_status': 'projection_only',
        },
    ]
    annotated = annotate_market_publication_candidates([base], sg_picks=sg_picks)[0]
    ledger = [{**base, 'market_publications': annotated['market_publication_candidates']}]
    feed_candidate = {
        'top_daily_picks': [], 'prime_picks': [], 'value_picks': [],
        'ace_picks': [], 'doubles_picks': [], 'sg_picks': sg_picks,
        'market_selection': {'publication_schema': 1},
    }
    assert validate_market_publication_candidate(feed_candidate, ledger) == 2
    confirmed, count = confirm_market_publications(
        ledger, feed_candidate, datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
    )
    assert count == 2

    completed = match_factory('completed-sg', 'A', 'B', 'A', day=20)
    completed.provider_payload = {'id': 'sg-event'}
    completed.scheduled_at = scheduled
    completed.stats = {
        'total_sets': 3.0, 'total_games': 30.0,
        'p1_sets_won': 2, 'p2_sets_won': 1,
    }
    settled = reconcile_ledger(
        confirmed, [], [completed], datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    )
    publications = {p['section']: p for p in settled[0]['market_publications']}
    assert publications['sets']['result']['status'] == 'hit'
    assert publications['games']['result']['status'] == 'hit'

    public = serving_feed(
        settled, SimpleNamespace(version='test'), [completed], {}, [],
        datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc),
    )
    assert len(public['results']) == 1
    assert {p['section'] for p in public['results'][0]['market_publications']} == {'sets', 'games'}
    assert public['betting_performance']['projections']['overall']['n'] == 2


def test_public_results_keep_all_history_but_strip_private_feature_payload():
    rows = []
    for index in range(3104):
        event = f"hist-{index}"
        row = _market_row(event_id=event)
        row["issued_at"] = "2026-09-18T08:00:00+00:00"
        row["scheduled_at"] = "2026-09-18T15:00:00+00:00"
        row["result"] = {
            "winner_id": "A", "correct": True,
            "settled_at": "2026-09-18T17:00:00+00:00",
            "scheduled_at": "2026-09-18T15:00:00+00:00",
        }
        row["signals"] = [{"huge_private_feature": "x" * 2000}]
        row["market_publications"] = [{
            "schema": 1,
            "publication_key": f"top_daily:match_winner:2026-09-18:{event}:A",
            "selection_key": f"match_winner:2026-09-18:{event}:A",
            "section": "top_daily",
            "market": "match_winner",
            "selection": "Alpha",
            "selection_id": "A",
            "odds": 1.9,
            "model_probability": .8,
            "issued_at": "2026-09-18T08:00:00+00:00",
            "publication_status": "published",
            "result": {
                "winner_id": "A", "correct": True, "staked_units": 1.0,
                "return_units": 1.9, "profit_units": .9,
                "settled_at": "2026-09-18T17:00:00+00:00",
                "scheduled_at": "2026-09-18T15:00:00+00:00",
            },
        }]
        rows.append(row)

    feed = serving_feed(
        rows, SimpleNamespace(version="test"), [], {}, [],
        datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc),
    )
    assert len(feed["results"]) == 3104
    assert feed["results_meta"]["settled_total"] == 3104
    assert len(json.dumps(feed, separators=(",", ":")).encode("utf-8")) < 10 * 1024 * 1024
    assert all("signals" not in row and "quality" not in row for row in feed["results"])
    assert all(row["market_publications"] for row in feed["results"])
