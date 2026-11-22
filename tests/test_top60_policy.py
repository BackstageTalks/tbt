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
    assert [r['event_id'] for r in out['top_daily_picks']] == ['4', '2', '1', '0', '3']
    assert [r['event_id'] for r in _daily_rows(out)] == ['4', '2', '1', '0', '3']
    changed = deepcopy(rows)
    changed[0]['betting']['odds'] = 1.75
    assert [r['event_id'] for r in select_market_sections(changed)['top_daily_picks']] == ['4', '2', '1', '0', '3']


def test_top_five_ranks_main_tours_before_challenger_and_excludes_itf():
    from test_top_priority_policy import verified_w35, pick
    rows = [
        verified_w35("itf", .99),
        pick("challenger", .94, "Challenger"),
        pick("wta", .60, "WTA"),
        pick("atp", .61, "ATP"),
        pick("extra", .62, "ATP"),
        pick("last", .63, "Challenger"),
    ]
    before = deepcopy(rows)
    out = select_market_sections(rows)
    expected = ["extra", "atp", "wta", "challenger", "last"]
    assert [r["event_id"] for r in out["top_daily_picks"]] == expected
    assert [r["event_id"] for r in _daily_rows(out)] == expected
    assert out["market_selection"]["top_daily_rule"]["limit"] == 5
    assert out["market_selection"]["top_daily_rule"]["daily_minimum_target"] == 3
    assert out["market_selection"]["top_daily_rule"]["no_forced_fill"] is True
    assert rows == before


def test_low_itf_m15_w15_remain_protected_pending_evidence():
    from test_top_priority_policy import pick
    m15 = pick("m15", .99, "ITF Men")
    m15["tournament"] = "ITF M15 Monastir"
    w15 = pick("w15", .99, "ITF Women")
    w15["tournament"] = "ITF W15 Monastir"
    for row in (m15, w15):
        row["quality"]["feature_evidence"] = {
            "serve_return_known_both": True,
            "surface_serve_return_known_both": True,
        }
    out = select_market_sections([m15, w15])
    assert out["top_daily_picks"] == []
    assert out["market_selection"]["top_daily_rule"]["competition_priority"] == [
        ["ATP", "WTA"], ["Challenger", "WTA 125", "BJK Cup", "Davis Cup"]
    ]
    assert out["market_selection"]["selection_counts"]["top_daily_shortfall"] == 3
