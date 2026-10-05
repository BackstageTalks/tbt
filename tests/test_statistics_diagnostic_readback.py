from tbt.data.provider_context import minimize_provider_payload


def test_statistics_missing_reasons_survive_repeated_canonical_compaction():
    raw={'_tbt_statistics':{'schema':3,'event_id':'12','status':'unavailable',
        'reason':'missing_unambiguous_all_period','period_labels':['1','2'],
        'unsupported_keys':['Games won','totalPointsWon'], 'raw_response':{'secret':'do not retain'}},
        'provider_response':{'large':'do not retain'}}
    compact=minimize_provider_payload(raw)
    assert compact['_tbt_statistics']['reason']=='missing_unambiguous_all_period'
    assert compact['_tbt_statistics']['period_labels']==['1','2']
    assert compact['_tbt_statistics']['unsupported_keys']==['Games won','totalPointsWon']
    assert 'raw_response' not in compact['_tbt_statistics']
    assert 'provider_response' not in compact
    assert minimize_provider_payload(compact)==compact


def test_diagnostics_are_bounded_and_ignore_arbitrary_payload_values():
    marker={'reason':'x'*1000,'unsupported_keys':[{'raw':'ignore'},None,True]+['a'*200]+[str(i) for i in range(80)],
        'period_labels':['1','1']+[str(i) for i in range(40)]}
    compact=minimize_provider_payload({'_tbt_statistics':marker})['_tbt_statistics']
    assert len(compact['reason'])==128
    assert len(compact['unsupported_keys'])==40
    assert all(len(x)<=96 for x in compact['unsupported_keys'])
    assert len(compact['period_labels'])==20
    assert compact['period_labels'].count('1')==1
