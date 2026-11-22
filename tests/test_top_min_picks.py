"""Owner-gated daily TOP minimum (TBT_TOP_MIN_PICKS) with emergency top-up.

Defaults (flags unset) must reproduce today's behaviour. Hard guards (identity,
price integrity, pre-start evidence, competition approval, odds >= 1.50) are never relaxed.
"""
import copy

import pytest

from test_market_selection import row
from tbt.services import market_anchored_rank as mar
from tbt.services.market_selection import select_market_sections


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (mar.ENV_RANK, mar.ENV_FILL, mar.ENV_TOP_SIDE, mar.ENV_TOP_MIN_PICKS):
        monkeypatch.delenv(name, raising=False)


def _slate():
    return [
        row('n1', .80, 1.60, 2.40), row('n2', .78, 1.55, 2.50),                  # normal TOP (public p >= .60)
        row('s1', .58, 1.55, 2.60), row('s2', .57, 1.62, 2.40),                  # below model floor, market agrees
        row('s3', .56, 1.70, 2.25), row('s4', .55, 1.75, 2.20),
        row('t1', .80, 1.60, 2.40, surface1=4),                                  # thin surface history (>= 3)
        row('t2', .80, 1.58, 2.45, surface1=2),                                  # too thin: never admitted
    ]


def _ids(result):
    return [c['event_id'] for c in result['top_daily_picks']]


def _find(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find(v, key)
            if r is not None:
                return r
    return None


def test_top_min_picks_parsing_and_fail_safe(monkeypatch):
    assert mar.top_min_picks(3) == 3
    for bad in ('', 'x', '2', '11', '-1', '4.5'):
        monkeypatch.setenv(mar.ENV_TOP_MIN_PICKS, bad)
        assert mar.top_min_picks(3) == 3
    monkeypatch.setenv(mar.ENV_TOP_MIN_PICKS, '5')
    assert mar.top_min_picks(3) == 5


def test_defaults_unchanged_and_only_normal_picks():
    base = select_market_sections(copy.deepcopy(_slate()))
    assert set(_ids(base)) == {'n1', 'n2'}
    assert _find(base['market_selection'], 'daily_minimum_target') == 3


def test_min_picks_alone_does_not_add_tips_but_reports_shortfall(monkeypatch):
    monkeypatch.setenv(mar.ENV_TOP_MIN_PICKS, '5')
    result = select_market_sections(copy.deepcopy(_slate()))
    assert set(_ids(result)) == {'n1', 'n2'}
    assert _find(result['market_selection'], 'daily_minimum_target') == 5
    assert _find(result['market_selection'], 'top_daily_shortfall') == 3


def test_min_picks_with_emergency_fill_reaches_five_without_relaxing_hard_guards(monkeypatch):
    monkeypatch.setenv(mar.ENV_TOP_MIN_PICKS, '5')
    monkeypatch.setenv(mar.ENV_FILL, '1')
    monkeypatch.setenv(mar.ENV_RANK, 'market_anchored')
    result = select_market_sections(copy.deepcopy(_slate()))
    ids = _ids(result)
    assert len(ids) == 5 and len(set(ids)) == 5
    assert {'n1', 'n2'} <= set(ids)
    assert 't2' not in ids                                     # surface history < 3 stays out
    tiers = {c['event_id']: c['selection_tier'] for c in result['top_daily_picks']}
    assert tiers['n1'] != mar.EMERGENCY_TIER and tiers['n2'] != mar.EMERGENCY_TIER
    assert sum(t == mar.EMERGENCY_TIER for t in tiers.values()) == 3
    assert all(c['odds'] >= 1.5 for c in result['top_daily_picks'])


def test_thin_surface_card_is_admitted_only_via_emergency(monkeypatch):
    monkeypatch.setenv(mar.ENV_TOP_MIN_PICKS, '8')
    monkeypatch.setenv(mar.ENV_FILL, '1')
    result = select_market_sections(copy.deepcopy(_slate()))
    ids = _ids(result)
    assert 't1' in ids and 't2' not in ids
    tiers = {c['event_id']: c['selection_tier'] for c in result['top_daily_picks']}
    assert tiers['t1'] == mar.EMERGENCY_TIER


def test_short_supply_returns_what_exists_and_never_crashes(monkeypatch):
    monkeypatch.setenv(mar.ENV_TOP_MIN_PICKS, '10')
    monkeypatch.setenv(mar.ENV_FILL, '1')
    result = select_market_sections(copy.deepcopy(_slate()[:3]))
    assert 3 >= len(_ids(result)) >= 1


def test_workflow_gates_top_min_picks_behind_owner_approval():
    from pathlib import Path
    text = Path('.github/workflows/data.yml').read_text(encoding='utf-8')
    line = [ln.strip() for ln in text.splitlines() if ln.strip().startswith('TBT_TOP_MIN_PICKS:')]
    assert len(line) == 1
    assert 'TBT_TOP_MIN_PICKS_OWNER_APPROVED' in line[0] and "'true'" in line[0] and "|| ''" in line[0]
