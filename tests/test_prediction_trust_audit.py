from copy import deepcopy
from test_selection_reliability_replay import candidate, settled, snapshot
from scripts.audit_prediction_trust import analyze


def item(event, raw=.8):
    row = candidate(event, raw=raw)
    row['created_at'] = '2026-11-02T06:00:00+00:00'
    row['competition'] = 'ITF Men'
    row['tournament'] = 'ITF M15 Test'
    return row


def test_unresolved_top_candidate_not_replaced_by_settled_fourth():
    rows = [item(str(i), .9-i*.03) for i in range(4)]
    report = analyze([snapshot(rows)], [settled(str(i)) for i in range(1,4)])
    top = report['models']['v7.2.1-frozen']['raw_top_3']
    assert top['selected'] == 3 and top['settled'] == 2
    assert top['positions']['1']['settled'] == 0
    assert report['cohorts']['M15']['statistics'] == {'not_recorded':4}


def test_price_and_outcome_changes_do_not_change_selected_position_counts():
    rows = [item(str(i), .9-i*.03) for i in range(4)]
    first = analyze([snapshot(rows)], [settled(str(i)) for i in range(4)])
    for row in rows:
        row['priced'] = False
        row['betting'] = None
    second = analyze([snapshot(rows)], [settled(str(i),winner='player-b') for i in range(4)])
    a = first['models']['v7.2.1-frozen']['raw_top_3']
    b = second['models']['v7.2.1-frozen']['raw_top_3']
    assert a['mean_probability'] == b['mean_probability']
    assert a['selected'] == b['selected'] == 3
    assert a['hit_rate'] == 1 and b['hit_rate'] == 0


def test_duplicate_and_future_prediction_excluded():
    a = item('a')
    future = item('future')
    future['created_at'] = '2026-11-02T08:00:00+00:00'
    result = analyze([snapshot([a,deepcopy(a),future])], [settled('a')])
    assert result['eligible_candidates'] == 1
    assert result['diagnostics']['duplicate_event_in_anchor'] == 1
    assert result['diagnostics']['missing_or_future_prediction_time'] == 1
