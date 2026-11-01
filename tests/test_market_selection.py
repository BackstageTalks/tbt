from datetime import datetime, timezone
import pytest

from tbt.services.market_selection import (
    betting_day_bounds,
    build_selection_candidate_snapshot,
    decimal_odds,
    enrich_current_betting_day_odds,
    extract_match_winner_odds,
    select_market_sections,
)


def row(event_id, probability, odds, opponent_odds, *, depth=.9, surface1=12, surface2=12, matches1=50, matches2=50, rank1=None, rank2=None):
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
        'player1': {'id': 'p1', 'name': 'Alpha', 'probability': p1, 'rank': rank1},
        'player2': {'id': 'p2', 'name': 'Beta', 'probability': p2, 'rank': rank2},
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


def test_candidate_snapshot_keeps_selected_and_unselected_without_post_match_fields():
    selected = row('selected-top', .72, 1.60, 2.50, depth=1.0)
    unpriced = row('unpriced', .73, 1.70, 2.30, depth=.95)
    unpriced.pop('betting', None)
    unpriced.pop('match_winner_market', None)
    # Deliberately inject fields that must never enter replay evidence.
    selected['result'] = {'correct': True}
    selected['stats'] = {'p1_aces': 99}
    snap = build_selection_candidate_snapshot(
        [selected, unpriced], generated_at=datetime(2026, 10, 8, 6, 30, tzinfo=timezone.utc)
    )
    assert snap['scope'] == {
        'all_singles_selector_inputs': 2,
        'priced_match_winner_inputs': 1,
        'selected_public_sections': 1,
        'post_match_fields_excluded': True,
    }
    rows = {item['event_id']: item for item in snap['rows']}
    assert rows['selected-top']['selected_section'] == 'top_daily'
    assert rows['selected-top']['selection_tier'] == 'fallback'
    assert rows['unpriced']['priced'] is False
    assert rows['unpriced']['selected_section'] is None
    serialized = str(snap).lower()
    assert 'correct' not in serialized
    assert 'p1_aces' not in serialized


def test_decimal_odds_supports_fractional_and_decimal():
    assert decimal_odds('7/10') == 1.7
    assert decimal_odds(1.85) == 1.85
    assert decimal_odds('0.85') is None


@pytest.mark.parametrize('level', ['envelope', 'market', 'choice'])
@pytest.mark.parametrize('flag', [True, 'true', 'false', None, 0, 1])
def test_unavailable_odds_never_enter_current_market(level, flag):
    payload = {'markets': [{'marketName': 'Full time', 'suspended': False, 'choices': [
        {'name': '1', 'fractionalValue': '4/5', 'suspended': False},
        {'name': '2', 'fractionalValue': '1/1', 'suspended': False},
    ]}]}
    target = {'envelope': payload, 'market': payload['markets'][0],
              'choice': payload['markets'][0]['choices'][0]}[level]
    target['suspended'] = flag
    assert extract_match_winner_odds(payload, 'Alpha', 'Beta') is None


def test_suspended_market_does_not_hide_separate_available_market():
    choices = [{'name': '1', 'fractionalValue': '4/5'},
               {'name': '2', 'fractionalValue': '1/1'}]
    payload = {'markets': [
        {'marketName': 'Full time', 'suspended': True, 'choices': choices},
        {'marketName': 'Full time', 'suspended': False, 'choices': choices},
    ]}
    assert extract_match_winner_odds(payload, 'Alpha', 'Beta')['player1_odds'] == 1.8


@pytest.mark.parametrize('sources,accepted', [
    ((7, 8), False), ((7, None), False), ((None, 7), False),
    ((7, '7'), True), ((0, 0), True), ((None, None), True),
])
def test_two_way_odds_do_not_invent_source_attribution(sources, accepted):
    payload = {'markets': [{'marketName': 'Full time', 'choices': [
        {'name': '1', 'fractionalValue': '4/5', 'sourceId': sources[0]},
        {'name': '2', 'fractionalValue': '1/1', 'sourceId': sources[1]},
    ]}]}
    result = extract_match_winner_odds(payload, 'Alpha', 'Beta')
    assert (result is not None) is accepted
    if accepted:
        assert result['source_id'] == sources[0]
        assert result['source_id_known'] is (sources[0] is not None)


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


def test_retired_top200_cannot_claim_ranked_picks_from_active_sections():
    rows = [
        row('ranked-short', .75, 1.30, 3.40, depth=1.0, rank1=150, rank2=420),
        row('ranked-value', .72, 1.90, 2.00, depth=1.0, rank1=360, rank2=88),
        row('ranked-top', .70, 1.60, 2.50, depth=1.0, rank1=199, rank2=260),
    ]
    sections = select_market_sections(rows)
    assert sections['top200_picks'] == []
    assert [item['event_id'] for item in sections['prime_picks']] == ['ranked-short']
    assert [item['event_id'] for item in sections['value_picks']] == ['ranked-value']
    assert [item['event_id'] for item in sections['top_daily_picks']] == ['ranked-top']
    meta = sections['market_selection']
    assert meta['selection_policy'] == 'active_value_top_prime_v16'
    assert meta['exclusive_assignment']['priority'] == ['value', 'top_daily', 'prime']
    assert 'top200_rule' not in meta


def test_retired_top200_never_caps_ranked_candidate_supply():
    rows = [
        row(f'ranked-{i}', .80 - i * .01, 1.60, 2.50, depth=1.0, rank1=100 + i, rank2=500)
        for i in range(7)
    ]
    sections = select_market_sections(rows)
    assert sections['top200_picks'] == []
    assert [item['event_id'] for item in sections['top_daily_picks']] == [
        f'ranked-{i}' for i in range(3)
    ]


def test_probability_first_odds_buckets_match_product_policy():
    rows = [
        row('prime', .72, 1.30, 2.70),
        row('top', .76, 1.50, 2.55),
        row('value', .70, 1.90, 2.05),  # symmetric gap ~7.6%, close odds
        row('top-not-value', .74, 1.90, 2.40),  # gap >15%, remains Top
    ]
    sections = select_market_sections(rows)
    assert [x['event_id'] for x in sections['prime_picks']] == ['prime']
    assert [x['event_id'] for x in sections['value_picks']] == ['value']
    assert [x['event_id'] for x in sections['top_daily_picks']] == ['top', 'top-not-value']
    meta = sections['market_selection']
    assert meta['selection_policy'] == 'active_value_top_prime_v16'
    assert meta['value_rule']['assignment_priority'] == 1
    assert meta['value_rule']['max_two_way_odds_difference'] == .15
    assert meta['top_daily_rule']['value_priority_exclusion'] is True


def test_prime_65_and_value_65_remain_while_top_never_falls_below_70():
    rows = [
        row('p649-prime', .649, 1.40, 3.10, depth=1.0),
        row('p649-top', .649, 1.70, 2.20, depth=1.0),
        row('v599', .599, 1.90, 2.00, depth=1.0),
        row('v600', .60, 1.90, 2.00, depth=1.0),
        row('v650', .65, 1.90, 2.00, depth=1.0),
        row('p650', .65, 1.60, 2.30, depth=1.0),
    ]
    sections = select_market_sections(rows, prime_min_probability=.50, top_min_probability=.50, value_min_probability=.50)
    assert [x['event_id'] for x in sections['value_picks']] == ['v650']
    # TOP no longer promotes 65% to VIP; PRIME and VALUE remain unchanged.
    assert sections['top_daily_picks'] == []
    assert sections['prime_picks'] == []
    assert sections['value_picks'][0]['probability'] == .65
    assert sections['market_selection']['selection_counts']['top_fallback_added'] == 0
    assert sections['market_selection']['selection_counts']['top_below_three_after_70'] is True


def test_blinq_probability_shrinks_raw_confidence_by_data_depth():
    shallow = row('shallow90', .90, 1.90, 2.00, depth=.30, surface1=20, surface2=20)
    deep = row('deep90', .90, 1.90, 2.00, depth=1.0, surface1=20, surface2=20)
    sections = select_market_sections([shallow, deep])
    assert [x['event_id'] for x in sections['value_picks']] == ['deep90']
    assert abs(sections['value_picks'][0]['probability'] - .90) < 1e-12

def test_low_data_depth_cannot_publish_high_probability_pick():
    rows = [
        row('fake90', .90, 1.40, 3.20, depth=.30, surface1=20, surface2=20),
        row('deep70', .70, 1.45, 3.20, depth=.90, surface1=20, surface2=20),
    ]
    sections = select_market_sections(rows)
    assert sections['top_daily_picks'] == []
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
    assert sections['market_selection']['exclusive_assignment']['priority'][:2] == ['value', 'top_daily']



def test_top_does_not_relax_when_three_core_picks_exist():
    rows = [row(f'core{i}', .80 + i*.01, 1.60 + i*.01, 2.60, depth=1.0) for i in range(3)]
    rows += [row('fallback', .75, 1.70, 2.50, depth=1.0)]
    sections = select_market_sections(rows)
    ids = [x['event_id'] for x in sections['top_daily_picks']]
    assert 'fallback' not in ids
    assert len(ids) == 3
    assert sections['market_selection']['selection_counts']['top_fallback_added'] == 0


def test_odds_150_belongs_to_top_not_prime():
    sections = select_market_sections([row('boundary', .72, 1.50, 2.60, depth=1.0)])
    assert sections['prime_picks'] == []
    assert [x['event_id'] for x in sections['top_daily_picks']] == ['boundary']

def test_value_close_odds_uses_symmetric_15_percent_rule():
    close = row('close', .70, 1.80, 2.05, depth=1.0)   # 12.99%
    far = row('far', .70, 1.80, 2.15, depth=1.0)      # 17.72%
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
    all_rows = sections['top200_picks'] + sections['prime_picks'] + sections['top_daily_picks'] + sections['value_picks']
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


def test_exhausted_budget_stops_outbound_attempts_but_still_uses_later_cached_quotes():
    from tbt.providers.budget import RequestBudgetExceeded

    class Exhausted:
        def __init__(self): self.called = []
        def event_odds(self, event_id, provider_id=1):
            self.called.append(event_id)
            raise RequestBudgetExceeded('exhausted')

    provider = Exhausted()
    rows = [row('first', .80, 1.8, 2.0), row('skip', .75, 1.8, 2.0), row('cached', .70, 1.8, 2.0)]
    cached = {'cached': _OddsProvider().event_odds('cached')}
    enriched, report = enrich_current_betting_day_odds(provider, rows, now=datetime(2026,9,7,8,tzinfo=timezone.utc), prefetched_payloads=cached)
    assert provider.called == ['first']
    assert report['stopped_on_budget'] is True
    assert report['skipped_budget'] == 2
    assert report['errors'] == 0
    assert report['odds_available'] == 1
    assert report['cache_hits'] == 1
    assert report['provider_call_attempts'] == 1


def test_odds_errors_are_classified_without_publishing_exception_body():
    class Broken:
        def event_odds(self, event_id, provider_id=1):
            raise RuntimeError('RapidAPI HTTP 404 for endpoint: private response text')

    _, report = enrich_current_betting_day_odds(Broken(), [row('first', .80, 1.8, 2.0)], now=datetime(2026,9,7,8,tzinfo=timezone.utc))
    assert report['error_types'] == {'http_404': 1}
    assert 'private response' not in str(report)


def test_odds_enrichment_covers_all_65_percent_value_candidates_before_prices_are_known():
    provider = _OddsProvider()
    rows = [
        row('eligible', .70, 1.60, 2.20, depth=.80, surface1=5, surface2=5),
        row('weak', .64, 1.60, 2.20, depth=1.0, surface1=20, surface2=20),
        row('shallow', .80, 1.60, 2.20, depth=.74, surface1=20, surface2=20),
        row('surface', .80, 1.60, 2.20, depth=1.0, surface1=2, surface2=20),
    ]
    for item in rows:
        item.pop('betting', None); item.pop('match_winner_market', None)
    enriched, report = enrich_current_betting_day_odds(provider, rows, now=datetime(2026,9,7,8,0,tzinfo=timezone.utc))
    assert provider.called == [('eligible', 1)]
    assert report['candidate_gate']['min_probability'] == .65
    assert report['candidate_gate']['min_data_depth'] == .75
    assert report['candidate_gate']['min_surface_matches_each'] == 3
    assert next(x for x in enriched if x['event_id'] == 'eligible').get('betting')


def test_top_dynamic_fallback_stops_at_first_tier_reaching_three():
    rows=[
        row('core1',.82,1.60,2.40,depth=1.0),row('core2',.81,1.55,2.50,depth=1.0),
        row('f78',.78,1.50,3.00,depth=1.0),row('short79',.79,1.49,3.00,depth=1.0),
        row('f75',.75,1.50,3.00,depth=1.0),row('f70',.70,1.52,3.00,depth=1.0),
        row('below-stop',.69,1.70,3.20,depth=1.0),
    ]
    sections=select_market_sections(rows)
    ids=[x['event_id'] for x in sections['top_daily_picks']]
    assert ids==['core1','core2','f78']
    assert 'short79' not in ids
    assert [x['event_id'] for x in sections['prime_picks']] == ['short79']
    assert 'below-stop' not in ids
    meta=sections['market_selection']['selection_counts']['top_fallback_applied']
    assert meta=={'step':1,'min_probability':.78,'min_odds':1.50}
    assert sections['market_selection']['top_daily_rule']['fallback_min_odds']==1.50
    assert sections['market_selection']['top_daily_rule']['fallback_only_if_core_count_below']==3
    assert sections['market_selection']['top_daily_rule']['probability_tiers']==[.80,.78,.75,.70]


def test_value_audit_reports_filter_bottlenecks_without_changing_selection():
    good = row('value-good', .72, 1.90, 2.00, depth=.90, surface1=10, surface2=10)
    low_odds = row('value-low-odds', .72, 1.70, 1.80, depth=.90, surface1=10, surface2=10)
    wide_market = row('value-wide', .72, 1.90, 2.50, depth=.90, surface1=10, surface2=10)
    shallow = row('value-shallow', .72, 1.90, 2.00, depth=.60, surface1=10, surface2=10)
    poor_surface = row('value-surface', .72, 1.90, 2.00, depth=.90, surface1=2, surface2=10)
    no_quote = row('value-no-quote', .72, 1.90, 2.00, depth=.90, surface1=10, surface2=10)
    no_quote.pop('betting', None)
    no_quote.pop('match_winner_market', None)

    sections = select_market_sections([
        good, low_odds, wide_market, shallow, poor_surface, no_quote,
    ])

    assert [item['event_id'] for item in sections['value_picks']] == ['value-good']
    audit = sections['market_selection']['value_audit']
    assert audit['selection_unchanged'] is True
    assert audit['model_rows'] == 6
    assert audit['real_match_winner_quote_attached'] == 5
    assert audit['missing_real_match_winner_quote'] == 1
    assert audit['qualified'] == 1
    assert audit['thresholds'] == {
        'min_probability': .65,
        'min_data_depth': .75,
        'min_surface_matches_each': 3,
        'min_odds': 1.80,
        'max_two_way_odds_difference': .15,
    }
    failures = audit['failure_counts_nonexclusive']
    assert failures['odds_below_min'] >= 1
    assert failures['odds_spread_above_max'] >= 1
    assert failures['data_depth_below_min'] >= 1
    assert failures['surface_sample_below_min'] >= 1


def test_prime_display_ranking_blends_probability_and_relative_odds_without_changing_pool():
    rows = [
        row("elite-low-price", .90, 1.08, 4.00, depth=1.0),
        row("strong-tiny-price", .86, 1.02, 5.00, depth=1.0),
        row("strong-better-price", .85, 1.49, 2.80, depth=1.0),
        row("mid-price", .84, 1.20, 3.80, depth=1.0),
        row("weak-high-price", .74, 1.44, 2.90, depth=1.0),
    ]
    sections = select_market_sections(rows)
    ids = [x["event_id"] for x in sections["prime_picks"]]
    assert set(ids) == {x["event_id"] for x in rows}
    assert ids.index("elite-low-price") < ids.index("weak-high-price")
    assert ids.index("strong-better-price") < ids.index("strong-tiny-price")
    rule = sections["market_selection"]["prime_rule"]
    assert rule["display_ranking_only"] is True
    assert rule["eligibility_pool_unchanged"] is True
    assert rule["display_weights"] == {"probability_percentile": .75, "odds_percentile": .25}


def test_uncapped_odds_enrichment_attempts_every_eligible_match_before_budget():
    provider = _OddsProvider()
    rows = [
        row(f"uncapped-{i}", .75 + i * .01, 1.8, 2.2, depth=.95,
            surface1=10, surface2=10)
        for i in range(5)
    ]
    for item in rows:
        item.pop("betting", None)
        item.pop("match_winner_market", None)
    enriched, report = enrich_current_betting_day_odds(
        provider, rows, now=datetime(2026, 9, 7, 8, tzinfo=timezone.utc),
        max_events=-1,
    )
    assert len(provider.called) == 5
    assert report["eligible_candidates"] == 5
    assert report["limited_out"] == 0
    assert report["odds_available"] == 5
    assert all(item.get("betting") for item in enriched)


def test_top_all_above_80_no_three_cap_and_true_probability_shown():
    rows = [row(f"strong{i}", .91 - .01*i, 1.60, 2.60, depth=1.0) for i in range(6)]
    rows += [row("fallback78", .78, 1.75, 3.00, depth=1.0)]
    section = select_market_sections(rows)
    picks = section["top_daily_picks"]
    assert len(picks) == 6
    assert all(x["probability"] >= .80 for x in picks)
    assert "fallback78" not in [x["event_id"] for x in picks]
    assert section["market_selection"]["selection_counts"]["active_top_probability_floor"] == .80
    assert section["market_selection"]["top_daily_rule"]["all_qualifying_above_active_tier"]


def test_top_first_threshold_with_three_78s_keeps_all_above_floor():
    rows = [
        row("a80", .81, 1.60, 3.00, depth=1.0),
        row("b78", .78, 1.60, 3.00, depth=1.0),
        row("c78", .79, 1.60, 3.00, depth=1.0),
        row("d75", .75, 1.60, 3.00, depth=1.0),
    ]
    result = select_market_sections(rows)
    assert [x["event_id"] for x in result["top_daily_picks"]] == ["a80","c78","b78"]
    assert result["market_selection"]["selection_counts"]["active_top_probability_floor"] == .78


def test_top_relaxes_to_75_then_70_only_for_target_three_not_below():
    rows = [
        row("a80", .80, 1.60, 3.00, depth=1.0),
        row("b78", .78, 1.60, 3.00, depth=1.0),
        row("c75", .75, 1.60, 3.00, depth=1.0),
        row("d70", .70, 1.60, 3.00, depth=1.0),
    ]
    result = select_market_sections(rows)
    assert [x["event_id"] for x in result["top_daily_picks"]] == ["a80","b78","c75"]
    assert result["market_selection"]["selection_counts"]["active_top_probability_floor"] == .75
    rows[2] = row("c69", .69, 1.60, 3.00, depth=1.0)
    result = select_market_sections(rows)
    assert [x["event_id"] for x in result["top_daily_picks"]] == ["a80","b78","d70"]
    assert result["market_selection"]["selection_counts"]["active_top_probability_floor"] == .70
    rows[3] = row("d69", .69, 1.60, 3.00, depth=1.0)
    result = select_market_sections(rows)
    assert [x["event_id"] for x in result["top_daily_picks"]] == ["a80","b78"]
    assert result["market_selection"]["selection_counts"]["top_below_three_after_70"] is True


def test_top_70_fallback_never_bypasses_data_depth_surface_odds():
    rows = [
        row("valid", .75, 1.50, 3.00, depth=1.0, surface1=5, surface2=5),
        row("short", .85, 1.49, 3.00, depth=1.0),
        row("shallow", .90, 1.60, 3.00, depth=.60),
        row("no-surface", .90, 1.60, 3.00, depth=1.0, surface1=3),
    ]
    result = select_market_sections(rows)
    assert [x["event_id"] for x in result["top_daily_picks"]] == ["valid"]
    assert result["market_selection"]["selection_counts"]["top_below_three_after_70"] is True
