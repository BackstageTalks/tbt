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
    matches1=50,
    matches2=50,
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
            'player1': {'matches': matches1, 'surface_matches': surface1},
            'player2': {'matches': matches2, 'surface_matches': surface2},
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
        row('top-floor-pass', .71, 1.35, .75, depth=1.0, surface1=20, surface2=20),
        row('top-probability-fail', .67, 2.20, .40, depth=1.0, surface1=20, surface2=20),
        row('depth-fail', .90, 1.40, .76, depth=.79, surface1=20, surface2=20),
        row('surface-fail', .90, 1.55, .74, depth=1.0, surface1=4, surface2=20),
    ]
    sections = select_market_sections(rows)
    assert [x['event_id'] for x in sections['prime_picks']] == ['prime-safe']
    assert [x['event_id'] for x in sections['top_daily_picks']] == ['top-balanced', 'top-floor-pass']
    assert [x['event_id'] for x in sections['value_picks']] == ['top-probability-fail', 'value-edge']
    assert sections['market_selection']['prime_rule']['min_probability'] == .85
    assert sections['market_selection']['prime_rule']['hard_odds_band'] is False
    assert sections['market_selection']['top_daily_rule']['product_label'] == 'Top Bets'
    assert sections['market_selection']['top_daily_rule']['preferred_probability'] == .75
    assert sections['market_selection']['top_daily_rule']['secondary_probability'] == .72
    assert sections['market_selection']['top_daily_rule']['standard_probability'] == .70
    assert sections['market_selection']['top_daily_rule']['target_count'] == 10
    assert sections['market_selection']['top_daily_rule']['min_probability'] == .68
    assert sections['market_selection']['top_daily_rule']['min_odds'] == 1.20
    assert sections['market_selection']['top_daily_rule']['min_edge'] is None
    assert sections['market_selection']['top_daily_rule']['min_expected_value'] is None
    assert sections['market_selection']['top_daily_rule']['edge_ev_role'] == 'diagnostic_only'
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


def test_top_bets_rank_probability_first_and_ignore_edge_ev_for_eligibility():
    rows = [
        # Lower probability has spectacular edge/EV, but must not outrank 71%.
        row('p68-big-value', .68, 2.40, .40, depth=1.0, surface1=20, surface2=20),
        row('p71-low-price', .71, 1.28, .82, depth=.90, surface1=8, surface2=8),
        row('p70', .70, 1.55, .75, depth=.95, surface1=15, surface2=15),
        row('p69', .69, 1.90, .55, depth=1.0, surface1=25, surface2=25),
    ]
    sections = select_market_sections(rows)
    assert [x['event_id'] for x in sections['top_daily_picks']] == [
        'p71-low-price', 'p70', 'p69', 'p68-big-value'
    ]


def test_top_bets_use_data_quality_then_odds_only_as_tiebreakers():
    rows = [
        row('depth-low', .70, 2.20, .50, depth=.81, surface1=30, surface2=30, matches1=100, matches2=100),
        row('depth-high', .70, 1.25, .80, depth=.95, surface1=6, surface2=6, matches1=30, matches2=30),
        row('surface-high', .69, 1.30, .80, depth=.90, surface1=20, surface2=18, matches1=40, matches2=40),
        row('surface-low', .69, 2.50, .40, depth=.90, surface1=8, surface2=8, matches1=100, matches2=100),
        row('overall-high', .68, 1.25, .80, depth=.90, surface1=10, surface2=10, matches1=80, matches2=75),
        row('overall-low', .68, 2.50, .40, depth=.90, surface1=10, surface2=10, matches1=30, matches2=30),
    ]
    sections = select_market_sections(rows)
    assert [x['event_id'] for x in sections['top_daily_picks']] == [
        'depth-high', 'depth-low', 'surface-high', 'surface-low', 'overall-high', 'overall-low'
    ]


def test_top_bets_fill_to_ten_from_68_floor_without_lower_probability_displacing_higher():
    rows = [
        row(f'p{i}', prob, 1.20 + i * .05, .80, depth=.9, surface1=10, surface2=10)
        for i, prob in enumerate([.76, .74, .73, .72, .715, .71, .705, .70, .69, .68, .675])
    ]
    sections = select_market_sections(rows)
    probs = [x['probability'] for x in sections['top_daily_picks']]
    assert len(probs) == 10
    assert probs == sorted(probs, reverse=True)
    assert probs[-1] == .68


def test_top_bets_keep_entire_tier_when_target_is_reached_without_default_hard_cap():
    rows = [
        row(f'p{i}', .80 - i * .002, 1.30 + i * .01, .75, depth=.95, surface1=20, surface2=20)
        for i in range(12)
    ]
    sections = select_market_sections(rows, prime_min_probability=.99)
    assert len(sections['top_daily_picks']) == 12
    cascade = sections['market_selection']['top_cascade']
    assert cascade['target_count'] == 10
    assert cascade['applied_floor'] == .75
    assert cascade['selected_before_optional_hard_limit'] == 12
    assert sections['market_selection']['top_daily_rule']['limit'] is None


def test_top_bets_cascade_stops_at_first_tier_that_reaches_ten_and_keeps_whole_tier():
    rows = []
    rows += [row(f'a{i}', .79 - i * .005, 1.35, .75, depth=.95, surface1=20, surface2=20) for i in range(6)]
    rows += [row(f'b{i}', .74 - i * .002, 1.40, .75, depth=.95, surface1=20, surface2=20) for i in range(8)]
    rows += [row(f'c{i}', .71 - i * .002, 1.45, .75, depth=.95, surface1=20, surface2=20) for i in range(5)]
    sections = select_market_sections(rows, prime_min_probability=.99)
    selected = sections['top_daily_picks']
    assert len(selected) == 14
    assert all(card['probability'] >= .72 for card in selected)
    assert all(not card['event_id'].startswith('c') for card in selected)
    assert sections['market_selection']['top_cascade']['applied_floor'] == .72


def test_section_limits_do_not_reserve_unpublished_rows_from_lower_priority_sections():
    rows = [
        row(f'top-value-{i}', .80 - i * .01, 2.00, .50, depth=.95, surface1=20, surface2=20)
        for i in range(11)
    ]
    sections = select_market_sections(rows, top_limit=10, prime_min_probability=.99)
    assert len(sections['top_daily_picks']) == 10
    assert len(sections['value_picks']) == 1
    assert sections['value_picks'][0]['event_id'] == 'top-value-10'
    all_rows = sections['top_daily_picks'] + sections['value_picks']
    assert len({(x['event_id'], x['betting']['selection_id']) for x in all_rows}) == 11
    assignment = sections['market_selection']['exclusive_assignment']
    assert assignment['limit_aware'] is True
    assert assignment['limited_out_by_section']['top_daily'] == 1


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
