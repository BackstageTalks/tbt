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


def test_prime_top_and_value_follow_distinct_working_policy():
    rows = [
        row('prime-safe', .90, 1.35, .76, depth=.9, surface1=18, surface2=9),
        row('top-balanced', .78, 1.62, .60, depth=.9, surface1=12, surface2=8),
        row('value-edge', .64, 1.95, .52, depth=.8, surface1=5, surface2=5),
        row('prime-negative-ev', .90, 1.05, .82, depth=1.0, surface1=30, surface2=30),
        row('top-probability-fail', .71, 1.75, .58, depth=1.0, surface1=20, surface2=20),
        row('depth-fail', .90, 1.40, .76, depth=.79, surface1=20, surface2=20),
        row('surface-fail', .90, 1.55, .74, depth=1.0, surface1=4, surface2=20),
    ]
    sections = select_market_sections(rows)
    assert [x['event_id'] for x in sections['prime_picks']] == ['prime-safe']
    assert [x['event_id'] for x in sections['top_daily_picks']] == ['top-balanced']
    assert [x['event_id'] for x in sections['value_picks']] == ['value-edge']
    assert sections['market_selection']['prime_rule']['min_probability'] == .85
    assert sections['market_selection']['prime_rule']['hard_odds_band'] is False
    assert sections['market_selection']['top_daily_rule']['product_label'] == 'Top Bets'
    assert sections['market_selection']['top_daily_rule']['min_odds'] == 1.50
    assert sections['market_selection']['value_rule']['min_odds'] == 1.80


def test_sections_are_mutually_exclusive_with_prime_then_top_then_value_priority():
    rows = [
        row('qualifies-all', .90, 2.00, .50, depth=1.0, surface1=20, surface2=20),
        row('top-and-value', .80, 1.90, .50, depth=1.0, surface1=20, surface2=20),
        row('value-only', .65, 1.95, .50, depth=.9, surface1=10, surface2=10),
    ]
    sections = select_market_sections(rows)
    assert {x['event_id'] for x in sections['prime_picks']} == {'qualifies-all'}
    assert {x['event_id'] for x in sections['top_daily_picks']} == {'top-and-value'}
    assert {x['event_id'] for x in sections['value_picks']} == {'value-only'}

    all_rows = sections['prime_picks'] + sections['top_daily_picks'] + sections['value_picks']
    identities = {(x['event_id'], x['betting']['selection_id']) for x in all_rows}
    assert len(all_rows) == len(identities)
    assignment = sections['market_selection']['exclusive_assignment']
    assert assignment['enabled'] is True
    assert assignment['priority'] == ['prime', 'top_daily', 'value']
    assert sections['market_selection']['selection_counts']['duplicates_removed'] == 3


def test_value_requires_price_edge_and_ev_not_market_closeness():
    rows = [
        row('good', .60, 2.00, .50, depth=.9, surface1=8, surface2=8),
        row('low-odds', .60, 1.79, .50, depth=.9, surface1=8, surface2=8),
        row('low-edge', .60, 2.00, .57, depth=.9, surface1=8, surface2=8),
        row('low-ev', .59, 1.80, .53, depth=.9, surface1=8, surface2=8),
        row('weak-model', .54, 2.10, .45, depth=.9, surface1=8, surface2=8),
        row('poor-depth', .65, 2.00, .50, depth=.74, surface1=8, surface2=8),
        row('poor-surface', .65, 2.00, .50, depth=.9, surface1=2, surface2=30),
    ]
    sections = select_market_sections(rows)
    assert {x['event_id'] for x in sections['value_picks']} == {'good'}
    rule = sections['market_selection']['value_rule']
    assert rule['min_probability'] == .55
    assert rule['min_data_depth'] == .75
    assert rule['min_surface_matches_each'] == 3
    assert rule['min_edge'] == .05
    assert rule['min_expected_value'] == .08


def test_market_publication_candidates_have_exactly_one_primary_section_and_do_not_leak_into_cards():
    from tbt.services.market_selection import annotate_market_publication_candidates

    rows = [
        row('qualifies-all', .90, 2.00, .50),
        row('top-value', .80, 1.90, .50),
        row('value-only', .65, 1.95, .50),
    ]
    annotated = annotate_market_publication_candidates(rows)
    by_id = {item['event_id']: item for item in annotated}
    assert [p['section'] for p in by_id['qualifies-all']['market_publication_candidates']] == ['prime']
    assert [p['section'] for p in by_id['top-value']['market_publication_candidates']] == ['top_daily']
    assert [p['section'] for p in by_id['value-only']['market_publication_candidates']] == ['value']
    for item in annotated:
        assert len(item['market_publication_candidates']) <= 1
        for publication in item['market_publication_candidates']:
            assert publication['issued_at'] is None
            assert publication['publication_status'] == 'pending'
            assert publication['primary_section'] == publication['section']
            assert publication['selection_key'].startswith(f"match_winner:2026-09-07:{item['event_id']}:")

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


def test_odds_enrichment_uses_broad_value_floor_before_final_section_rules():
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
    assert provider.called == [('surface', 1), ('shallow', 1), ('eligible', 1), ('weak', 1)]
    assert report['candidates'] == 4
    assert report['odds_requested'] == 4
    assert report['candidate_gate'] == {
        'min_probability': .55,
        'min_data_depth': .75,
        'min_surface_matches_each': 3,
    }
    assert all(next(x for x in enriched if x['event_id'] == event_id).get('betting') for event_id in ('eligible','weak','shallow','surface'))
    final_sections = select_market_sections(enriched)
    assert final_sections['prime_picks'] == []
    assert final_sections['top_daily_picks'] == []
    assert final_sections['value_picks'] == []
