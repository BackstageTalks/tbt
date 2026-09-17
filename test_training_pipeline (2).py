from tbt.data.provider_context import minimize_provider_payload


def test_compact_provider_context_preserves_small_team_country_evidence_for_player_master():
    raw = {
        'homeTeam': {'id': 11, 'name':'A', 'country': {'alpha3':'GER'}, 'huge':'drop-me'},
        'awayTeam': {'id': 22, 'name':'B', 'country': {'alpha2':'US'}},
        'massive': [1,2,3],
    }
    compact = minimize_provider_payload(raw)
    assert compact['homeTeam'] == {'id':11,'name':'A','country':{'alpha3':'GER'}}
    assert compact['awayTeam'] == {'id':22,'name':'B','country':{'alpha2':'US'}}
    assert 'massive' not in compact and 'huge' not in compact['homeTeam']
