from datetime import datetime, timezone

from tbt.services.market_selection import (
    betting_day_bounds,
    decimal_odds,
    extract_match_winner_odds,
    select_market_sections,
)


def row(event_id, probability, odds, implied, *, depth=.8, gap=.10):
    p1 = probability
    p2 = 1 - probability
    if p1 >= p2:
        winner = 'p1'
        fair = implied
    else:
        winner = 'p2'
        fair = implied
    return {
        'event_id': event_id,
        'scheduled_at': '2026-09-07T12:00:00+00:00',
        'tour': 'ATP',
        'tournament': 'Test',
        'surface': 'hard',
        'player1': {'id': 'p1', 'name': 'Alpha', 'probability': p1},
        'player2': {'id': 'p2', 'name': 'Beta', 'probability': p2},
        'winner_id': winner,
        'confidence': max(p1, p2),
        'data_depth': depth,
        'betting': {
            'market': 'match_winner',
            'selection': 'Alpha' if winner == 'p1' else 'Beta',
            'selection_id': winner,
            'odds': odds,
            'fair_implied_probability': fair,
            'model_probability': max(p1, p2),
            'edge': max(p1, p2) - fair,
            'expected_value': max(p1, p2) * odds - 1,
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


def test_top_daily_and_value_rules_are_distinct():
    rows = [
        row('a', .72, 1.65, .62, depth=.9, gap=.08),   # daily, not value (odds too low)
        row('b', .66, 1.90, .56, depth=.8, gap=.10),   # daily + value
        row('c', .64, 2.00, .55, depth=.2, gap=.10),   # value, but not daily depth
        row('d', .68, 1.95, .58, depth=.8, gap=.20),   # daily, not value gap
    ]
    sections = select_market_sections(rows)
    daily_ids = {x['event_id'] for x in sections['top_daily_picks']}
    value_ids = {x['event_id'] for x in sections['value_picks']}
    assert daily_ids == {'a', 'b', 'd'}
    assert value_ids == {'b', 'c'}
