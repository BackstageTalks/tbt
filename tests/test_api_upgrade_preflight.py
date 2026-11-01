from copy import deepcopy
import pytest
from scripts.api_upgrade_preflight import compare_calendars, check_point_in_time


def calendar():
    return {'events': [{'id': 1, 'home_id': 2, 'away_id': 3,
        'scheduled_at': '2026-01-02T12:00:00Z', 'discipline': 'singles', 'tour': 'ATP'}]}


def observation(kind='season'):
    return {'kind': kind, 'entity_id': 'p1', 'source_ref': 'fixture:test',
        'available_at': '2026-01-02T12:00:00Z', 'prediction_at': '2026-01-03T12:00:00Z',
        'coverage_end': '2026-01-01T12:00:00Z', 'source_match_id': 'old',
        'target_match_id': 'new', 'match_finished': True, 'completeness_verified': True,
        'provider_quote_at': '2026-01-02T11:00:00Z',
        'target_match_start': '2026-01-03T13:00:00Z', 'source_id': 1, 'suspended': False}


def test_calendar_equivalent_timezones():
    old = calendar()
    new = deepcopy(old)
    new['events'][0]['scheduled_at'] = '2026-01-02T13:00:00+01:00'
    assert compare_calendars(old, new)['passed']


@pytest.mark.parametrize('field,value', [('home_id', 8), ('discipline', 'doubles'),
    ('tour', 'WTA'), ('scheduled_at', '2026-01-02T13:00:00Z')])
def test_calendar_context_change(field, value):
    new = calendar()
    new['events'][0][field] = value
    assert not compare_calendars(calendar(), new)['passed']


def test_calendar_missing_added_empty_duplicate():
    empty = {'events': []}
    assert not compare_calendars(calendar(), empty)['passed']
    assert not compare_calendars(empty, calendar())['passed']
    assert not compare_calendars(empty, empty)['passed']
    duplicate = calendar()
    duplicate['events'] *= 2
    with pytest.raises(ValueError, match='Duplicate'):
        compare_calendars(calendar(), duplicate)


@pytest.mark.parametrize('kind', ['season', 'match_stats', 'pbp', 'odds'])
def test_chronology_valid(kind):
    assert check_point_in_time({'observations': [observation(kind)]})['passed']


@pytest.mark.parametrize('kind,field,value', [
    ('season', 'coverage_end', '2026-12-31T00:00:00Z'),
    ('season', 'available_at', '2026-01-03T12:00:00Z'),
    ('season', 'available_at', '2026-01-02T12:00:00'),
    ('match_stats', 'source_match_id', 'new'),
    ('match_stats', 'match_finished', False),
    ('pbp', 'completeness_verified', False),
    ('odds', 'provider_quote_at', None),
    ('odds', 'provider_quote_at', '2026-01-04T00:00:00Z'),
    ('odds', 'target_match_start', '2026-01-03T11:00:00Z'),
    ('odds', 'suspended', True), ('odds', 'source_id', None),
    ('season', 'source_ref', ''),
])
def test_chronology_rejects_unusable_evidence(kind, field, value):
    row = observation(kind)
    row[field] = value
    assert not check_point_in_time({'observations': [row]})['passed']
