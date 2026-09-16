from datetime import datetime, timezone

from tbt.services.market_selection import (
    betting_day_bounds,
    decimal_odds,
    enrich_current_betting_day_odds,
    extract_match_winner_odds,
    select_market_sections,
)


def row(event_id, probability, odds, opponent_odds, *, depth=.9, surface1=12, surface2=12, matches1=50, matches2=50):
    p1 = probability
    p2 = 1 - probability
    winner = 'p1' if p1 >= p2 else 'p2'
    selected_odds = odds
    market = {
        'player1_odds': selected_odds if winner == 'p1' else opponent_odds,
        'player2_odds': opponent_odds if winner == 'p1' else selected_odds,
    }
    raw1, raw2 = 1 / market['player1_odds'], 1 / market['player2_odds']
    total = raw1 + raw2
    market['player1_implied_probability'] = raw1 / total
    market['player2_implied_probability'] = raw2 / total
    fair = market['player1_implied_probability'] if winner == 'p1' else market['player2_implied_probability']
    model_probability = max(p1, p2)
    return {
        'event_id': event_id,
        'scheduled_at': '2026-09-07T12:00:00+00:00',
        'tour': 'ATP', 'tournament': 'Test', 'surface': 'hard',
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
            'odds': selected_odds,
            'fair_implied_probability': fair,
            'model_probability': model_probability,
            'edge': model_probability - fair,
            'expected_value': model_probability * selected_odds - 1,
            'provider_id': 1,
            'betting_day': '2026-09-07',
        },
        'match_winner_market': market,
    }


def test_decimal_odds_supports_fractional_and_decimal():
    assert decimal_odds('7/10') == 1.7
    assert decimal_odds(1.85) == 1.85
    assert decimal_odds('0.85') is None


def test_extract_match_winner_odds_from_nested_provider_shape():
    payload = {'markets': [{'marketName': 'Full time', 'choices': [
        {'choiceName': 'Alpha', 'fractionalValue': 1.80, 'initialFractionalValue': 1.75},
        {'choiceName': 'Beta', 'fractionalValue': 2.05, 'initialFractionalValue': 2.10},
    ]}]}
    market = extract_match_winner_odds(payload, 'Alpha', 'Beta')
    assert market is not None
    assert market['player1_odds'] == 1.80
    assert market['player2_odds'] == 2.05
    assert abs(market['player1_implied_probability'] + market['player2_implied_probability'] - 1) < 1e-12


def test_betting_day_uses_six_am_bratislava_boundary():
    now = datetime(2026, 9, 7, 3, 0, tzinfo=timezone.utc)
    start, end, key = betting_day_bounds(now, start_hour=6)
    assert key == '2026-09-06'
    assert start.isoformat() == '2026-09-06T04:00:00+00:00'
    assert end.isoformat() == '2026-09-07T04:00:00+00:00'


def test_probability_first_odds_buckets_match_product_policy():
    rows = [
        row('prime', .72, 1.49, 2.70),
        row('top', .76, 1.50, 2.55),
        row('value', .70, 1.90, 2.05),  # symmetric gap ~7.6%, close odds
        row('top-not-value', .74, 1.90, 2.40),  # gap >15%, remains Top
    ]
    sections = select_market_sections(rows)
    assert [x['event_id'] for x in sections['prime_picks']] == ['prime']
    assert [x['event_id'] for x in sections['value_picks']] == ['value']
    assert [x['event_id'] for x in sections['top_daily_picks']] == ['top', 'top-not-value']
    meta = sections['market_selection']
    assert meta['selection_policy'] == 'probability_first_odds_buckets_v10_core68_fallback65'
    assert meta['value_rule']['assignment_priority'] == 1
    assert meta['value_rule']['max_two_way_odds_difference'] == .15
    assert meta['top_daily_rule']['value_priority_exclusion'] is True


def test_prime_top_core68_fallback65_and_value60_policy():
    rows = [
        row('p649-prime', .649, 1.40, 3.10, depth=1.0),
        row('p649-top', .649, 1.70, 2.20, depth=1.0),
        row('v599', .599, 1.90, 2.00, depth=1.0),
        row('v600', .60, 1.90, 2.00, depth=1.0),
        row('p650', .65, 1.60, 2.30, depth=1.0),
    ]
    sections = select_market_sections(rows, prime_min_probability=.50, top_min_probability=.50, value_min_probability=.50)
    assert [x['event_id'] for x in sections['value_picks']] == ['v600']
    # There are fewer than five 68%+ Top picks, so a 65% row may fill the shortfall.
    assert [x['event_id'] for x in sections['top_daily_picks']] == ['p650']
    assert sections['prime_picks'] == []
    assert sections['value_picks'][0]['probability'] == .60
    assert sections['top_daily_picks'][0]['probability'] == .65
    assert sections['market_selection']['selection_counts']['top_fallback_65_679_added'] == 1


def test_blinq_probability_shrinks_raw_confidence_by_data_depth():
    shallow = row('shallow90', .90, 1.90, 2.00, depth=.30, surface1=20, surface2=20)
    deep = row('deep90', .90, 1.90, 2.00, depth=1.0, surface1=20, surface2=20)
    sections = select_market_sections([shallow, deep])
    assert [x['event_id'] for x in sections['value_picks']] == ['deep90']
    assert abs(sections['value_picks'][0]['probability'] - .90) < 1e-12

def test_low_data_depth_cannot_publish_high_probability_pick():
    rows = [
        row('fake90', .90, 1.40, 3.20, depth=.30, surface1=20, surface2=20),
        row('deep70', .70, 1.40, 3.20, depth=.90, surface1=20, surface2=20),
    ]
    sections = select_market_sections(rows)
    assert [x['event_id'] for x in sections['prime_picks']] == ['deep70']


def test_surface_depth_fails_closed():
    rows = [
        row('poor-surface-prime', .90, 1.40, 3.00, depth=1.0, surface1=4, surface2=20),
        row('poor-surface-value', .90, 1.90, 2.00, depth=1.0, surface1=2, surface2=20),
    ]
    sections = select_market_sections(rows)
    assert sections['prime_picks'] == []
    assert sections['value_picks'] == []


def test_value_has_priority_over_top_when_both_qualify():
    sections = select_market_sections([row('both', .80, 1.90, 2.00, depth=.95, surface1=20, surface2=20)])
    assert [x['event_id'] for x in sections['value_picks']] == ['both']
    assert sections['top_daily_picks'] == []
    assert sections['market_selection']['exclusive_assignment']['priority'][0] == 'value'



def test_prime_top_do_not_use_65_679_fallback_when_five_core_picks_exist():
    rows = [row(f'core{i}', .70 + i*.01, 1.60 + i*.01, 2.60, depth=1.0) for i in range(5)]
    rows += [row('fallback', .67, 1.70, 2.50, depth=1.0)]
    sections = select_market_sections(rows)
    ids = [x['event_id'] for x in sections['top_daily_picks']]
    assert 'fallback' not in ids
    assert len(ids) == 5
    assert sections['market_selection']['selection_counts']['top_fallback_65_679_added'] == 0


def test_odds_150_belongs_to_top_not_prime():
    sections = select_market_sections([row('boundary', .72, 1.50, 2.60, depth=1.0)])
    assert sections['prime_picks'] == []
    assert [x['event_id'] for x in sections['top_daily_picks']] == ['boundary']

def test_value_close_odds_uses_symmetric_15_percent_rule():
    close = row('close', .70, 1.80, 2.05)   # 12.99%
    far = row('far', .70, 1.80, 2.15)      # 17.72%
    sections = select_market_sections([close, far])
    assert [x['event_id'] for x in sections['value_picks']] == ['close']
    assert [x['event_id'] for x in sections['top_daily_picks']] == ['far']


def test_ev_and_edge_do_not_control_publication():
    # Short price has negative EV under the model but still qualifies for Prime;
    # this is intentional because publication is probability+evidence+odds bucket.
    item = row('negative-ev-prime', .70, 1.20, 5.50, depth=.95, surface1=20, surface2=20)
    assert item['betting']['expected_value'] < 0
    sections = select_market_sections([item])
    assert [x['event_id'] for x in sections['prime_picks']] == ['negative-ev-prime']


def test_sections_remain_mutually_exclusive():
    rows = [row(f'e{i}', .70 + i*.01, 1.85 + i*.01, 1.95 + i*.01) for i in range(5)]
    sections = select_market_sections(rows)
    all_rows = sections['prime_picks'] + sections['top_daily_picks'] + sections['value_picks']
    identities = {(x['event_id'], x['betting']['selection_id']) for x in all_rows}
    assert len(all_rows) == len(identities)


class _OddsProvider:
    def __init__(self): self.called = []
    def event_odds(self, event_id, provider_id=1):
        self.called.append((event_id, provider_id))
        return {'markets': [{'marketName': 'Full time', 'choices': [
            {'choiceName': 'Alpha', 'fractionalValue': 1.55},
            {'choiceName': 'Beta', 'fractionalValue': 2.45},
        ]}]}


def test_odds_enrichment_covers_all_60_percent_value_candidates_before_prices_are_known():
    provider = _OddsProvider()
    rows = [
        row('eligible', .65, 1.60, 2.20, depth=.80, surface1=5, surface2=5),
        row('weak', .64, 1.60, 2.20, depth=1.0, surface1=20, surface2=20),
        row('shallow', .80, 1.60, 2.20, depth=.74, surface1=20, surface2=20),
        row('surface', .80, 1.60, 2.20, depth=1.0, surface1=2, surface2=20),
    ]
    for item in rows:
        item.pop('betting', None); item.pop('match_winner_market', None)
    enriched, report = enrich_current_betting_day_odds(provider, rows, now=datetime(2026,9,7,8,0,tzinfo=timezone.utc))
    assert provider.called == [('weak', 1), ('eligible', 1)]
    assert report['candidate_gate']['min_probability'] == .60
    assert report['candidate_gate']['min_data_depth'] == .75
    assert report['candidate_gate']['min_surface_matches_each'] == 3
    assert next(x for x in enriched if x['event_id'] == 'eligible').get('betting')
