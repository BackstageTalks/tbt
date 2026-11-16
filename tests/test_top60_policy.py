from copy import deepcopy

from test_market_selection import row
from tbt.services.market_selection import select_market_sections
from tbt.services.entitlements import _daily_rows


def test_top60_survives_member_filter_and_does_not_force_three():
    rows = [row('boundary', .60, 1.5, 2.6, depth=1),
            row('below', .5999, 1.6, 2.6, depth=1),
            row('shrunken', .62, 1.6, 2.6, depth=.8),
            row('short', .64, 1.49, 2.6, depth=1)]
    before = deepcopy(rows)
    out = select_market_sections(rows)
    assert [r['event_id'] for r in out['top_daily_picks']] == ['boundary']
    assert [r['event_id'] for r in _daily_rows(out)] == ['boundary']
    assert out['market_selection']['selection_counts']['top_daily_shortfall'] == 2
    assert rows == before


def test_top60_global_sports_order_cap_and_odds_independence():
    rows = [row(str(i), p, 1.6, 2.6, depth=1)
            for i, p in enumerate((.61, .62, .63, .64, .64))]
    rows[3]['competition'] = 'Challenger'
    out = select_market_sections(rows)
    assert [r['event_id'] for r in out['top_daily_picks']] == ['3', '4', '2']
    assert [r['event_id'] for r in _daily_rows(out)] == ['3', '4', '2']
    changed = deepcopy(rows)
    changed[0]['betting']['odds'] = 1.75
    assert [r['event_id'] for r in select_market_sections(changed)['top_daily_picks']] == ['3', '4', '2']
