from datetime import datetime, timezone

from tbt.services.market_selection import (
    betting_day_bounds,
    decimal_odds,
    enrich_current_betting_day_odds,
    extract_match_winner_odds,
    select_market_sections,
)


def row(
    event_id,
    probability,
    odds,
    implied,
    *,
    depth=.8,
    gap=.10,
    surface1=12,
    surface2=12,
    edge=None,
):
    p1 = probability
    p2 = 1 - probability
    if p1 >= p2:
        winner = 'p1'
        fair = implied
    else:
        winner = 'p2'
        fair = implied
    model_probability = max(p1, p2)
    actual_edge = model_probability - fair if edge is None else edge
    return {
        'event_id': event_id,
        'scheduled_at': '2026-09-07T12:00:00+00:00',
        'tour': 'ATP',
        'tournament': 'Test',
        'surface': 'hard',
        'player1': {'id': 'p1', 'name': 'Alpha', 'probability': p1},
        'player2': {'id': 'p2', 'name': 'Beta', 'probability': p2},
        'winner_id': winner,
        'confidence': model_probability,
        'data_depth': depth,
        'quality': {
            'player1': {'matches': 50, 'surface_matches': surface1},
            'player2': {'matches': 50, 'surface_matches': surface2},
            'surface_known': True,
        },
        'betting': {
            'market': 'match_winner',
            'selection': 'Alpha' if winner == 'p1' else 'Beta',
            'selection_id': winner,
            'odds': odds,
            'fair_implied_probability': fair,
            'model_probability': model_probability,
            'edge': actual_edge,
            'expected_value': model_probability * odds - 1,
            'provider_id': 1,
            'betting_day': '2026-09-07',
        },
        'match_winner_market': {
            'player1_implied_probability': .5 + gap / 2,
            'player2_implied_probability': .5 - gap / 2,
        },
    }


def test_decimal_odds_supports_fractional_and_decimal():
    assert decimal_odds('7/10') == 1.7
    assert decimal_odds(1.85) == 1.85
    assert decimal_odds('0.85') is None


def test_extract_match_winner_odds_from_nested_provider_shape():
    payload = {
        'markets': [
            {
                'marketName': 'Full time',
                'choices': [
                    {'choiceName': 'Alpha', 'fractionalValue': 1.80, 'initialFractionalValue': 1.75},
                    {'choiceName': 'Beta', 'fractionalValue': 2.05, 'initialFractionalValue': 2.10},
                ],
            },
            {
                'marketName': 'First set winner',
                'choices': [
                    {'choiceName': 'Alpha', 'fractionalValue': 1.55},
                    {'choiceName': 'Beta', 'fractionalValue': 2.45},
                ],
            },
        ]
    }
    market = extract_match_winner_odds(payload, 'Alpha', 'Beta')
    assert market is not None
    assert market['player1_odds'] == 1.80
    assert market['player2_odds'] == 2.05
    assert market['player1_opening_odds'] == 1.75
    assert market['player2_opening_odds'] == 2.10
    assert abs(market['player1_implied_probability'] + market['player2_implied_probability'] - 1) < 1e-12


def test_betting_day_uses_six_am_bratislava_boundary():
    now = datetime(2026, 9, 7, 3, 0, tzinfo=timezone.utc)  # 05:00 CEST
    start, end, key = betting_day_bounds(now, start_hour=6)
    assert key == '2026-09-06'
    assert start.isoformat() == '2026-09-06T04:00:00+00:00'
    assert end.isoformat() == '2026-09-07T04:00:00+00:00'


def test_daily_and_prime_are_one_quality_pool_split_only_by_price():
    rows = [
        row('daily', .84, 1.42, .70, depth=.9, surface1=18, surface2=9),
        row('prime', .81, 1.65, .60, depth=.8, surface1=5, surface2=8),
        row('too-cheap', .91, 1.20, .82, depth=1.0, surface1=30, surface2=30),
        row('probability-fail', .77, 1.45, .68, depth=1.0, surface1=20, surface2=20),
        row('depth-fail', .88, 1.40, .76, depth=.79, surface1=20, surface2=20),
        row('surface-fail', .90, 1.55, .74, depth=1.0, surface1=4, surface2=20),
    ]
    sections = select_market_sections(rows)
    assert [x['event_id'] for x in sections['top_daily_picks']] == ['daily']
    assert [x['event_id'] for x in sections['prime_picks']] == ['prime']
    assert sections['market_selection']['main_candidate_rule'] == {
        'min_probability': .78,
        'min_data_depth': .8,
        'min_surface_matches_each': 5,
        'edge_filter': False,
    }


def test_daily_boundary_is_125_through_150_and_prime_starts_above_150():
    rows = [
        row('low', .85, 1.249, .78),
        row('daily-min', .85, 1.25, .78),
        row('daily-max', .85, 1.50, .70),
        row('prime-min', .85, 1.5001, .70),
        row('prime-high', .85, 2.40, .45),
    ]
    sections = select_market_sections(rows)
    assert {x['event_id'] for x in sections['top_daily_picks']} == {'daily-min', 'daily-max'}
    assert {x['event_id'] for x in sections['prime_picks']} == {'prime-min', 'prime-high'}


def test_value_is_close_market_analysis_and_edge_is_display_only():
    rows = [
        row('close', .64, 1.92, .51, depth=.9, gap=.10),
        row('close-negative-stored-edge', .62, 1.88, .52, depth=.9, gap=.08, edge=-.07),
        row('not-close', .70, 1.75, .55, depth=.9, gap=.16),
        row('weak-model', .59, 1.95, .50, depth=.9, gap=.04),
        row('poor-surface', .70, 1.90, .52, depth=.9, gap=.06, surface1=4, surface2=30),
    ]
    sections = select_market_sections(rows)
    value_ids = {x['event_id'] for x in sections['value_picks']}
    assert value_ids == {'close', 'close-negative-stored-edge'}
    by_id = {x['event_id']: x for x in sections['value_picks']}
    assert by_id['close-negative-stored-edge']['edge'] == -.07
    assert by_id['close-negative-stored-edge']['close_market'] is True
    rule = sections['market_selection']['value_rule']
    assert rule['edge_filter'] is False
    assert rule['edge_display_only'] is True
    assert rule['max_implied_probability_gap'] == .15


def test_market_publication_candidates_track_daily_prime_value_membership_without_leaking_into_cards():
    from tbt.services.market_selection import annotate_market_publication_candidates

    rows = [
        row('daily', .84, 1.42, .70, gap=.30),  # Daily only
        row('prime-value', .81, 1.70, .55, gap=.10),  # Prime + close-market Value
        row('value-only', .65, 1.90, .52, gap=.08),  # Below main 78%, still Value
    ]
    annotated = annotate_market_publication_candidates(rows)
    by_id = {item['event_id']: item for item in annotated}
    assert {p['section'] for p in by_id['daily']['market_publication_candidates']} == {'top_daily'}
    assert {p['section'] for p in by_id['prime-value']['market_publication_candidates']} == {'prime', 'value'}
    assert {p['section'] for p in by_id['value-only']['market_publication_candidates']} == {'value'}
    for publication in by_id['prime-value']['market_publication_candidates']:
        assert publication['issued_at'] is None
        assert publication['publication_status'] == 'pending'
        assert publication['selection_key'].startswith('match_winner:2026-09-07:prime-value:')

    sections = select_market_sections(annotated)
    for key in ('top_daily_picks', 'prime_picks', 'value_picks'):
        assert all('market_publication_candidates' not in card for card in sections[key])


class _OddsProvider:
    def __init__(self):
        self.called = []

    def event_odds(self, event_id, provider_id=1):
        self.called.append((event_id, provider_id))
        return {
            'markets': [{
                'marketName': 'Full time',
                'choices': [
                    {'choiceName': 'Alpha', 'fractionalValue': 1.60},
                    {'choiceName': 'Beta', 'fractionalValue': 2.20},
                ],
            }]
        }


def test_odds_enrichment_spends_calls_only_on_broad_60_80_5_candidate_gate():
    provider = _OddsProvider()
    rows = [
        row('eligible', .61, 1.60, .60, depth=.8, surface1=5, surface2=5),
        row('weak', .59, 1.60, .60, depth=1.0, surface1=20, surface2=20),
        row('shallow', .80, 1.60, .60, depth=.79, surface1=20, surface2=20),
        row('surface', .80, 1.60, .60, depth=1.0, surface1=4, surface2=20),
    ]
    # Enrichment starts from model predictions that do not yet contain odds.
    for item in rows:
        item.pop('betting', None)
        item.pop('match_winner_market', None)
    enriched, report = enrich_current_betting_day_odds(
        provider,
        rows,
        now=datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc),
        max_events=150,
    )
    assert provider.called == [('eligible', 1)]
    assert report['candidates'] == 1
    assert report['odds_requested'] == 1
    assert report['candidate_gate'] == {
        'min_probability': .60,
        'min_data_depth': .80,
        'min_surface_matches_each': 5,
    }
    assert next(x for x in enriched if x['event_id'] == 'eligible').get('betting')
    assert not next(x for x in enriched if x['event_id'] == 'weak').get('betting')
