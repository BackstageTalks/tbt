from tbt.services.entitlements import filter_feed_for_access


def _row(i, odds, prob, prefix='d'):
    return {
        'event_id': f'{prefix}{i}', 'pick': f'P{i}', 'odds': odds, 'probability': prob,
        'player1': {'name': f'A{i}', 'probability': prob},
        'player2': {'name': f'B{i}', 'probability': 1-prob},
    }


def _feed():
    return {
        'prime_picks': [_row(1,1.30,.83),_row(2,1.45,.78),_row(3,1.49,.74)],
        'top_daily_picks': [_row(4,1.50,.73),_row(5,1.80,.70),_row(6,2.10,.69)],
        'value_picks': [_row(6,2.10,.69), _row(7,1.90,.64,'v')],
        'doubles_picks': [], 'ace_picks': [], 'sg_picks': [], 'upcoming': []
    }


def _ui(visible=1, enabled=True, blur=True):
    plans={p:{'visible_rows':visible,'blur_remaining':blur,'tab_enabled':enabled} for p in ('trial','expired','rookie','pro','elite','legend','goat')}
    tabs={k:{'enabled':True,'plans':plans} for k in ('daily','value','ace','games')}
    return {'dashboard':{'daily_hub':{'enabled':True,'tabs':tabs}}}


def test_daily_combines_prime_top_filters_low_odds_and_value_duplicates():
    data, manifest=filter_feed_for_access(_feed(), {'status':'active','plan':'elite'})
    ids=[r['event_id'] for r in data['daily_picks']]
    assert 'd1' not in ids  # 1.30 excluded by Daily >= 1.45
    assert 'd6' not in ids  # Value has priority
    assert ids[:3] == ['d2','d3','d4']
    assert manifest['sections']['daily']['total'] == 4


def test_runtime_admin_rule_can_narrow_to_zero_without_sending_rows():
    data, manifest=filter_feed_for_access(_feed(), {'status':'active','plan':'pro'}, _ui(0, True, True))
    assert data['daily_picks'] == []
    assert manifest['sections']['daily']['visible_picks'] == 0
    assert manifest['sections']['daily']['blur_remaining'] is True
    assert manifest['sections']['daily']['total'] == 4


def test_runtime_admin_can_disable_tab_entirely():
    data, manifest=filter_feed_for_access(_feed(), {'status':'active','plan':'pro'}, _ui(5, False, True))
    assert data['daily_picks'] == []
    assert manifest['sections']['daily']['enabled'] is False
