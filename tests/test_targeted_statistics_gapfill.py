from datetime import datetime, timedelta, timezone

from tbt.services.statistics_gapfill import event_id, missing_fields, retry_due
from tbt.services.statistics_enrichment import StatisticsEnricher, STATISTICS_SCHEMA_VERSION


def test_conflicting_event_ids_are_not_selected_by_precedence(match_factory):
    m = match_factory('x', 'A', 'B', 'A')
    m.provider_payload = {'id': '1', '_tbt_event_identity': {'event_id': '2'}}
    assert event_id(m) is None
    m.provider_payload = {'_tbt_event_identity': {'event_id': '2'}}
    assert event_id(m) == '2'


def test_partial_available_rows_can_retry_but_not_each_tick(match_factory):
    now = datetime.now(timezone.utc)
    m = match_factory('x', 'A', 'B', 'A')
    m.provider_payload = {'id': '123', '_tbt_statistics': {
        'schema': STATISTICS_SCHEMA_VERSION, 'event_id': '123', 'status': 'available',
        'fetched_at': (now - timedelta(days=31)).isoformat()}}
    assert retry_due(m, STATISTICS_SCHEMA_VERSION, now)
    m.provider_payload['_tbt_statistics']['fetched_at'] = now.isoformat()
    assert not retry_due(m, STATISTICS_SCHEMA_VERSION, now)
    m.provider_payload['_tbt_statistics']['fetched_at'] = 'bad'
    assert not retry_due(m, STATISTICS_SCHEMA_VERSION, now)


def test_rates_do_not_hide_missing_ace_and_df_fields(match_factory):
    m = match_factory('x', 'A', 'B', 'A')
    m.stats = {f'{p}_{f}': .5 for p in ('p1', 'p2')
               for f in ('service_points_won', 'return_points_won')}
    assert set(missing_fields(m)) == {'p1_aces','p2_aces','p1_double_faults','p2_double_faults'}



def test_targeted_collector_fills_ace_df_when_service_rates_are_ready(match_factory, tmp_path):
    class Provider:
        def __init__(self):
            self.calls = 0

        def _get(self, path, **kwargs):
            self.calls += 1
            assert path == '/api/tennis/event/123/statistics'
            return {'statistics': [{'period': 'ALL', 'groups': [{'statisticsItems': [
                {'name': 'Aces', 'home': '5', 'away': '3'},
                {'name': 'Double faults', 'home': '2', 'away': '1'}]}]}]}

    m = match_factory('x', 'A', 'B', 'A')
    m.stats = {f'{p}_{f}': .5 for p in ('p1', 'p2')
               for f in ('service_points_won', 'return_points_won')}
    m.provider_payload = {'id': '123', '_tbt_event_identity': {
        'event_id':'123', 'status':'finished', 'home':'A', 'away':'B'},
        '_tbt_statistics': {'schema': STATISTICS_SCHEMA_VERSION, 'event_id': '123',
                            'status': 'available',
                            'fetched_at': (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()}}
    provider = Provider()
    enricher = StatisticsEnricher(provider, tmp_path/'cache.sqlite', targeted=True)
    try:
        assert enricher.enrich(m) == 'enriched'
        assert provider.calls == 1
        assert (m.stats['p1_aces'], m.stats['p2_aces']) == (5, 3)
        assert (m.stats['p1_double_faults'], m.stats['p2_double_faults']) == (2, 1)
    finally:
        enricher.close()


def test_conflicting_response_never_overwrites_or_adds_other_fields(match_factory, tmp_path):
    class Provider:
        calls = 0
        def _get(self, path, **kwargs):
            self.calls += 1
            return {'statistics': [{'period': 'ALL', 'groups': [{'statisticsItems': [
                {'name': 'Aces', 'home': '5', 'away': '3'},
                {'name': 'Double faults', 'home': '2', 'away': '1'}]}]}]}
    m = match_factory('x', 'A', 'B', 'A')
    m.stats = {'p1_aces': 4}
    m.provider_payload = {'id': '123', '_tbt_event_identity': {
        'event_id':'123', 'status':'finished', 'home':'A', 'away':'B'}}
    provider = Provider()
    enricher = StatisticsEnricher(provider, tmp_path/'cache.sqlite')
    try:
        assert enricher.enrich(m) == 'conflict'
        assert m.stats == {'p1_aces': 4}
        assert enricher.enrich(m) == 'cached'
        assert provider.calls == 1
    finally:
        enricher.close()


def test_targeted_queue_filters_cooldown_and_prioritizes_recent_gaps(match_factory):
    from datetime import date
    from download_tennis_history import _statistics_candidates
    old = match_factory('old', 'A', 'B', 'A')
    recent = match_factory('recent', 'A', 'B', 'A')
    recent.scheduled_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    missing = match_factory('missing', 'A', 'B', 'A')
    cached = match_factory('cached', 'A', 'B', 'A')
    for m in (old, recent, cached):
        m.provider_payload = {'id': '123'}
    cached.provider_payload['_tbt_statistics'] = {
        'schema':STATISTICS_SCHEMA_VERSION, 'event_id':'123', 'status':'unavailable',
        'fetched_at':datetime.now(timezone.utc).isoformat()}
    rows, plan = _statistics_candidates([old, missing, cached, recent],
        date(2022,1,1), date(2026,12,31), targeted=True)
    assert [m.match_id for m in rows] == ['recent', 'old']
    assert plan['skipped'] == {'missing_or_conflicting_event_id':1, 'retry_not_due':1}



def test_targeted_priority_values_quality_and_verified_identity(match_factory):
    from datetime import date
    from download_tennis_history import _statistics_candidates
    ready = match_factory('ready', 'A', 'B', 'A')
    incomplete = match_factory('incomplete', 'A', 'B', 'A')
    verified = match_factory('verified', 'A', 'B', 'A')
    unverified = match_factory('unverified', 'A', 'B', 'A')
    for m in (ready, incomplete, verified, unverified):
        m.scheduled_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        m.provider_payload = {'id': '123'}
    ready.stats = {f'{p}_{f}': .5 for p in ('p1', 'p2')
                   for f in ('service_points_won', 'return_points_won')}
    incomplete.stats = {'p1_service_points_won': .5, 'p1_return_points_won': .5,
                        'p2_aces': 2}
    verified.stats = {'p1_service_points_won': .5, 'p1_return_points_won': .5}
    unverified.stats = dict(verified.stats)
    verified.provider_payload['_tbt_event_identity'] = {
        'event_id': '123', 'status': 'finished', 'home': 'A', 'away': 'B'}
    ordered, _ = _statistics_candidates(
        [ready, incomplete, verified, unverified],
        date(2026, 1, 1), date(2026, 12, 31), targeted=True)
    names = [m.match_id for m in ordered]
    assert names.index('ready') > names.index('incomplete')
    assert names.index('verified') < names.index('unverified')


def test_readback_requires_all_exact_added_values(match_factory):
    import pytest
    from verify_targeted_statistics import verify_added_fields
    m = match_factory('x', 'A', 'B', 'A')
    m.stats = {'p1_aces': 0}
    assert verify_added_fields([m], {'x': {'p1_aces': 0}}) == 1
    with pytest.raises(ValueError):
        verify_added_fields([m], {'x': {'p1_aces': 1}})
    with pytest.raises(ValueError):
        verify_added_fields([], {'x': {'p1_aces': 0}})
    with pytest.raises(ValueError):
        verify_added_fields([m, m], {'x': {'p1_aces': 0}})
