from datetime import datetime, timedelta, timezone

from tbt.services.statistics_gapfill import event_id, missing_fields, retry_due, recent_score_identity_conflict
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


def test_targeted_outcome_evidence_separates_paid_gains_and_unavailable_reasons(match_factory):
    from collections import Counter
    from download_tennis_history import _record_targeted_statistics_outcome, _statistics_segment_yield

    segments = {}
    reasons = Counter()
    match = match_factory('audit', 'A', 'B', 'A')
    match.tour = 'atp'
    match.scheduled_at = datetime(2026, 5, 15, tzinfo=timezone.utc)
    _record_targeted_statistics_outcome(
        segments, reasons, match, 'enriched', 2,
        {'new_statistic_values': 8, 'new_quality_ready_rows': 1, 'new_ace_df_values': 4},
    )
    match.provider_payload = {'_tbt_statistics': {
        'status': 'unavailable', 'reason': 'no_supported_fields'}}
    _record_targeted_statistics_outcome(
        segments, reasons, match, 'unavailable', 1,
        {'new_statistic_values': 0, 'new_quality_ready_rows': 0, 'new_ace_df_values': 0},
    )
    # A cache/local hit must never be counted as provider yield.
    _record_targeted_statistics_outcome(
        segments, reasons, match, 'enriched', 0,
        {'new_statistic_values': 2, 'new_quality_ready_rows': 0, 'new_ace_df_values': 0},
    )
    data = _statistics_segment_yield(segments)['atp:2026']
    assert data['processed_matches'] == 3
    assert data['api_requests_including_retries'] == 3
    assert data['matches_with_provider_requests'] == 2
    assert data['status_enriched'] == 2
    assert data['status_unavailable'] == 1
    assert data['unavailable_no_supported_fields'] == 1
    assert reasons == {'no_supported_fields': 1}
    assert data['new_statistic_values'] == 10
    assert data['api_new_statistic_values'] == 8
    assert data['local_or_cache_new_statistic_values'] == 2
    assert data['api_new_quality_ready_rows'] == 1
    assert data['api_new_ace_df_values'] == 4
    assert data['api_new_statistic_values_per_1000_requests'] == 8000/3
    assert data['api_new_quality_ready_rows_per_1000_requests'] == 1000/3


def test_targeted_outcome_unknown_coverage_reason_and_zero_request_denominator(match_factory):
    from collections import Counter
    from download_tennis_history import _record_targeted_statistics_outcome, _statistics_segment_yield

    match = match_factory('audit', 'A', 'B', 'A')
    match.tour = 'wta'
    match.scheduled_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    match.provider_payload = {'_tbt_statistics': {'status':'unavailable',
                                                  'reason':'provider_private_data_secret'}}
    segments = {}
    reasons = Counter()
    _record_targeted_statistics_outcome(
        segments, reasons, match, 'unavailable', 0, {})
    data = _statistics_segment_yield(segments)['wta:2025']
    assert data['unavailable_unspecified'] == 1
    assert reasons == {'unspecified': 1}
    assert data['api_requests_including_retries'] == 0
    assert data['api_new_statistic_values_per_1000_requests'] is None
    assert data['api_new_quality_ready_rows_per_1000_requests'] is None


def test_hourly_priority_favors_verified_yield_over_depleted_atp_2025(match_factory):
    from datetime import date
    from download_tennis_history import _statistics_candidates

    def match(mid, tour, year, stats):
        m = match_factory(mid, 'A', 'B', 'A')
        m.tour = tour
        m.scheduled_at = datetime(year, 8, 17, tzinfo=timezone.utc)
        m.stats = stats
        m.provider_payload = {'id': str(500 + len(mid))}
        return m

    atp2025 = match('atp-2025', 'ATP', 2025, {'p1_service_points_won': .6})
    wta2024 = match('wta-2024', 'WTA', 2024, {'p1_service_points_won': .6})
    wta2026 = match('wta-2026', 'WTA', 2026, {})
    atp2025_ace = match('atp-2025-ace', 'ATP', 2025, {
        f'{p}_{k}': .6 for p in ('p1', 'p2')
        for k in ('service_points_won', 'return_points_won')
    })
    rows = [atp2025, wta2026, wta2024, atp2025_ace]
    default, _ = _statistics_candidates(rows, date(2024, 1, 1),
                                         date(2026, 12, 31), targeted=True)
    preferred, report = _statistics_candidates(
        rows, date(2024, 1, 1), date(2026, 12, 31),
        targeted=True, historical_high_yield=True,
    )
    assert default[0].match_id == 'wta-2026'
    assert preferred[0].match_id == 'wta-2024'
    assert preferred[-1].match_id == 'atp-2025-ace'
    assert report['preferred_verified_cohort'] == 'atp:2024:serve_return_incomplete'
    assert report['verified_high_yield_cohorts'] == [
        'atp:2024', 'wta:2023', 'wta:2024', 'wta:2022',
    ]
    assert report['historical_high_yield'] is True
    import pytest
    with pytest.raises(ValueError, match='requires identity-checked'):
        _statistics_candidates(rows, date(2024, 1, 1), date(2026, 12, 31),
                               historical_high_yield=True)


def test_hourly_97_percent_queue_gives_undercovered_atp_wta_years_a_budget_share(match_factory):
    from datetime import date
    from collections import Counter
    from download_tennis_history import _statistics_candidates

    rows = []
    cohorts = (("wta", 2024, 30), ("wta", 2023, 15),
               ("atp", 2022, 15), ("atp", 2025, 15))
    for tour, year, count in cohorts:
        for index in range(count):
            m = match_factory(f"{tour}-{year}-{index}", "A", "B", "A")
            m.tour = tour.upper()
            m.scheduled_at = datetime(year, 6, 1, tzinfo=timezone.utc) + timedelta(days=index)
            m.stats = {"p1_service_points_won": 0.6}
            m.provider_payload = {"id": str(1000 + len(rows))}
            rows.append(m)

    selected, report = _statistics_candidates(
        rows, date(2022, 1, 1), date(2026, 12, 31),
        targeted=True, historical_high_yield=True,
    )
    assert len(selected) == len(rows)
    assert len({m.match_id for m in selected}) == len(rows)
    # Initial baseline samples recent gaps while retaining older ATP/WTA work.
    first_twenty = Counter((m.tour.lower(), m.scheduled_at.year)
                           for m in selected[:20])
    assert first_twenty == {
        ("wta", 2024): 9,
        ("wta", 2023): 3,
        ("atp", 2022): 1,
        ("atp", 2025): 7,
    }
    assert report["priority_policy"] == (
        "8_recent_verified_6_recent_gap_3_historic_verified_1_historic_gap_2_other"
    )
    assert report["recent_focus_years"] == [2024, 2025, 2026]
    assert report["planned_recent_baseline_share_if_all_families_available"] == 0.7
    assert sum(report["first_1000_by_tour_year"].values()) == len(rows)



def test_full_baseline_cycle_protects_recent_2024_2026_and_older_evidence(match_factory):
    from datetime import date
    from collections import Counter
    from download_tennis_history import _statistics_candidates

    # Supply all five lanes so empty-family fallthrough cannot mask a regression.
    cohorts = (
        ("WTA", 2024, False), ("ATP", 2024, False),
        ("WTA", 2025, False), ("WTA", 2026, False), ("ATP", 2026, False),
        ("WTA", 2023, False), ("WTA", 2022, False),
        ("ATP", 2022, False), ("ATP", 2025, True),
    )
    rows = []
    for tour, year, ready in cohorts:
        for n in range(30):
            row = match_factory(f"{tour}-{year}-{n}", "A", "B", "A")
            row.tour = tour
            row.scheduled_at = datetime(year, 8, 1, tzinfo=timezone.utc) + timedelta(days=n)
            row.stats = ({f"{p}_{field}": .5 for p in ("p1", "p2")
                         for field in ("service_points_won", "return_points_won")}
                         if ready else {"p1_service_points_won": .6})
            row.provider_payload = {"id": str(1000 + len(rows))}
            rows.append(row)
    ordered, plan = _statistics_candidates(
        rows, date(2022, 1, 1), date(2026, 12, 31),
        targeted=True, historical_high_yield=True,
    )
    first = ordered[:20]
    assert len(first) == 20
    assert len({row.match_id for row in ordered}) == len(rows)
    assert sum(row.scheduled_at.year >= 2024 for row in first) == 16
    assert sum(row.scheduled_at.year <= 2023 for row in first) == 4
    buckets = Counter((row.tour.lower(), row.scheduled_at.year) for row in first)
    assert buckets[("wta", 2024)] == 4
    assert buckets[("atp", 2024)] == 4
    assert buckets[("wta", 2025)] >= 1
    assert buckets[("wta", 2026)] >= 1
    assert buckets[("atp", 2026)] >= 1
    assert buckets[("wta", 2023)] >= 1
    assert buckets[("wta", 2022)] >= 1
    assert buckets[("atp", 2022)] == 1
    assert plan["recent_focus_years"] == [2024, 2025, 2026]
    assert sum(plan["first_1000_by_tour_year"].values()) == len(rows)


def test_high_yield_queue_prioritizes_independently_verified_player_pair(match_factory):
    from datetime import date
    from download_tennis_history import _statistics_candidates

    unverified = match_factory("unverified", "A", "B", "A")
    verified = match_factory("verified", "A", "B", "A")
    for m in (unverified, verified):
        m.tour = "ATP"
        m.scheduled_at = datetime(2025, 6, 1, tzinfo=timezone.utc)
        m.stats = {"p1_service_points_won": 0.6}
        m.provider_payload = {"id": "123"}
    verified.provider_payload["_tbt_event_identity"] = {
        "event_id": "123", "home": "A", "away": "B", "status": "finished"
    }
    selected, _ = _statistics_candidates(
        [unverified, verified], date(2025, 1, 1), date(2025, 12, 31),
        targeted=True, historical_high_yield=True,
    )
    assert [m.match_id for m in selected] == ["verified", "unverified"]


def test_wta_older_underserved_years_rotate_instead_of_starving(match_factory):
    from datetime import date
    from download_tennis_history import _statistics_candidates

    matches = []
    for year in (2023, 2024, 2025):
        for n in range(5):
            m = match_factory(f"wta-{year}-{n}", "A", "B", "A")
            m.tour = "WTA"
            m.scheduled_at = datetime(year, 8, 1, tzinfo=timezone.utc) + timedelta(days=n)
            m.provider_payload = {"id": str(year * 10 + n)}
            m.stats = {}
            matches.append(m)
    ordered, _ = _statistics_candidates(
        matches, date(2022, 1, 1), date(2025, 12, 31),
        targeted=True, historical_high_yield=True,
    )
    # Recent gaps get the front slots; older proven WTA work is still sampled.
    assert ordered[0].scheduled_at.year == 2024
    assert 2025 in [m.scheduled_at.year for m in ordered[:6]]
    assert 2023 in [m.scheduled_at.year for m in ordered[:6]]
    assert {m.scheduled_at.year for m in ordered[:12]} == {2023, 2024, 2025}



def test_high_yield_rotates_distinct_atp_wta_buckets_in_same_year(match_factory):
    from datetime import date
    from download_tennis_history import _statistics_candidates
    matches = []
    for tour in ('WTA', 'ATP'):
        for n in range(4):
            m = match_factory(f'{tour}-{n}', 'A', 'B', 'A')
            m.tour = tour
            m.scheduled_at = datetime(2024, 8, 1 + n, tzinfo=timezone.utc)
            m.stats = {}
            m.provider_payload = {'id': str(1000 + len(matches))}
            matches.append(m)
    ordered, _ = _statistics_candidates(
        matches, date(2024, 1, 1), date(2024, 12, 31),
        targeted=True, historical_high_yield=True,
    )
    assert [m.tour for m in ordered] == ['ATP', 'WTA'] * 4


def test_hourly_high_yield_flag_is_not_enabled_for_manual_operator_request():
    from pathlib import Path
    wf=(Path(__file__).resolve().parents[1] / '.github/workflows/data.yml').read_text()
    assert "BLINQ_AUTOFILL_HIGH_YIELD: ${{ inputs.hourly_autofill && inputs.mode == 'statistics' && 'true' || 'false' }}" in wf
    script=(Path(__file__).resolve().parents[1] / 'scripts/download_tennis_history.py').read_text()
    assert 'historical_high_yield=high_yield_setting == "true"' in script
    assert 'targeted_statistics' in script


def test_empty_provider_statistics_has_reason_and_cooldown(match_factory, tmp_path):
    class Provider:
        def __init__(self):
            self.calls = 0

        def _get(self, path, **kwargs):
            self.calls += 1
            assert path == '/api/tennis/event/123/statistics'
            return {'statistics': []}

    match = match_factory('empty-snapshot', 'A', 'B', 'A')
    match.stats = {}
    match.provider_payload = {'id': '123', '_tbt_event_identity': {
        'event_id': '123', 'status': 'finished', 'home': 'A', 'away': 'B',
    }}
    provider = Provider()
    enricher = StatisticsEnricher(provider, tmp_path / 'statistics.sqlite', targeted=True)
    try:
        assert enricher.enrich(match) == 'unavailable'
        marker = match.provider_payload['_tbt_statistics']
        assert marker['status'] == 'unavailable'
        assert marker['reason'] == 'empty_whole_match_statistics'
        assert enricher.enrich(match) == 'cached'
        assert provider.calls == 1
        assert match.stats == {}
    finally:
        enricher.close()


def test_provider_not_finished_is_reasoned_cooldown_not_repeated_detail(match_factory, tmp_path):
    class Provider:
        calls = 0

        def _get(self, path, **kwargs):
            self.calls += 1
            assert path == '/api/tennis/event/123'
            return {'event': {'status': {'type': 'inprogress'},
                              'homeTeam': {'id': 'A'}, 'awayTeam': {'id': 'B'}}}

    m = match_factory('provider-lag', 'A', 'B', 'A')
    m.provider_payload = {'id': '123'}
    m.stats = {}
    before = m.is_completed
    provider = Provider()
    enricher = StatisticsEnricher(provider, tmp_path / 'lag.sqlite', targeted=True)
    try:
        assert enricher.enrich(m) == 'unavailable'
        marker = m.provider_payload['_tbt_statistics']
        assert marker['status'] == 'unavailable'
        assert marker['reason'] == 'provider_event_not_finished'
        assert m.is_completed is before
        assert m.stats == {}
        assert retry_due(m, STATISTICS_SCHEMA_VERSION) is False
        assert enricher.enrich(m) == 'cached'
        assert provider.calls == 1
        assert '_tbt_event_identity' not in m.provider_payload
    finally:
        enricher.close()


def test_provider_coverage_reason_is_visible_in_segment_report(match_factory):
    from collections import Counter
    from download_tennis_history import _record_targeted_statistics_outcome
    reasons, segments = Counter(), {}
    m = match_factory('coverage', 'A', 'B', 'A')
    m.tour = 'WTA'
    m.provider_payload = {'_tbt_statistics': {
        'status': 'unavailable', 'reason': 'empty_whole_match_statistics'}}
    _record_targeted_statistics_outcome(segments, reasons, m, 'unavailable', 1, {})
    m.provider_payload['_tbt_statistics']['reason'] = 'provider_event_not_finished'
    _record_targeted_statistics_outcome(segments, reasons, m, 'unavailable', 1, {})
    assert reasons == {'empty_whole_match_statistics': 1, 'provider_event_not_finished': 1}
    assert segments[f'wta:{m.scheduled_at.year}']['unavailable_provider_event_not_finished'] == 1


def test_hourly_verified_atp_2024_leads_initial_evidence_order(match_factory):
    from datetime import date
    from download_tennis_history import _statistics_candidates

    rows = []
    for tour, year in (("WTA", 2024), ("ATP", 2024), ("WTA", 2023)):
        for n in range(4):
            m = match_factory(f"{tour}-{year}-{n}", "A", "B", "A")
            m.tour = tour
            m.scheduled_at = datetime(year, 6, n + 1, tzinfo=timezone.utc)
            m.stats = {"p1_service_points_won": 0.6}
            m.provider_payload = {"id": str(1000 + len(rows))}
            rows.append(m)
    ordered, plan = _statistics_candidates(
        rows, date(2023, 1, 1), date(2024, 12, 31),
        targeted=True, historical_high_yield=True,
    )
    assert (ordered[0].tour, ordered[0].scheduled_at.year) == ("ATP", 2024)
    assert plan["preferred_verified_cohort"] == "atp:2024:serve_return_incomplete"
    assert len({row.match_id for row in ordered}) == len(rows)


def test_wta_2025_eligible_probe_precedes_repeatedly_empty_2026_baseline(
    match_factory,
):
    from datetime import date
    from download_tennis_history import _statistics_candidates

    rows = []
    for tour, year in (("ATP", 2026), ("WTA", 2026), ("WTA", 2025)):
        for n in range(8):
            m = match_factory(f"{tour}-{year}-{n}", "A", "B", "A")
            m.tour = tour
            m.scheduled_at = datetime(year, 5, n + 1, tzinfo=timezone.utc)
            m.stats = {"p1_service_points_won": 0.6}
            m.provider_payload = {"id": str(2000 + len(rows))}
            rows.append(m)
    ordered, plan = _statistics_candidates(
        rows, date(2025, 1, 1), date(2026, 12, 31),
        targeted=True, historical_high_yield=True,
    )
    assert (ordered[0].tour, ordered[0].scheduled_at.year) == ("WTA", 2025)
    assert sum(row.scheduled_at.year == 2026 for row in ordered[:8]) > 0
    assert plan["eligibility_by_tour_year"]["wta:2025"]["eligible"] == 8
    assert len(ordered) == len(rows)


def test_wta_2025_ineligible_gaps_report_why_without_extra_api_calls(
    match_factory,
):
    from datetime import date
    from download_tennis_history import _statistics_candidates

    rows = []
    for n in range(3):
        m = match_factory(f"wta-ineligible-{n}", "A", "B", "A")
        m.tour = "WTA"
        m.scheduled_at = datetime(2025, 5, n + 1, tzinfo=timezone.utc)
        m.stats = {"p1_service_points_won": 0.6}
        rows.append(m)
    rows[0].provider_payload = {"id": "333"}
    rows[1].provider_payload = {}
    rows[2].provider_payload = {
        "id": "335",
        "_tbt_statistics": {
            "schema": STATISTICS_SCHEMA_VERSION, "event_id": "335",
            "status": "unavailable", "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    eligible, plan = _statistics_candidates(
        rows, date(2025, 1, 1), date(2025, 12, 31),
        targeted=True, historical_high_yield=True,
    )
    assert [row.match_id for row in eligible] == ["wta-ineligible-0"]
    assert plan["eligibility_by_tour_year"]["wta:2025"] == {
        "eligible": 1,
        "missing_or_conflicting_event_id": 1,
        "retry_not_due": 1,
    }


def _known_score_identity_conflict(match, *, fetched_at):
    match.provider_payload = {
        "id": "123",
        "_tbt_event_identity": {
            "event_id": "123", "home": "A", "away": "X", "status": "mismatch",
        },
        "_tbt_score": {
            "schema": 3, "event_id": "123", "status": "identity_mismatch",
            "identity_verified": False, "fetched_at": fetched_at,
        },
    }


def test_score_proven_identity_conflict_skips_paid_hourly_statistics(match_factory):
    from datetime import date
    from download_tennis_history import _statistics_candidates

    m = match_factory("conflict", "A", "B", "A")
    now = datetime.now(timezone.utc)
    _known_score_identity_conflict(m, fetched_at=now.isoformat())
    assert recent_score_identity_conflict(m, now=now)
    candidates, plan = _statistics_candidates([m], date(2020, 1, 1),
                                               date(2026, 12, 31), targeted=True)
    assert candidates == []
    assert plan["skipped"]["recent_identity_conflict"] == 1

    class NeverCallProvider:
        def _get(self, path, **kwargs):
            raise AssertionError("Recent score mismatch must not trigger API")

    # The direct collector also protects manual/non-targeted modes.
    from tempfile import TemporaryDirectory
    from pathlib import Path
    with TemporaryDirectory() as tmp:
        enricher = StatisticsEnricher(NeverCallProvider(), Path(tmp)/"stats.sqlite", targeted=True)
        try:
            assert enricher.enrich(m) == "cached"
        finally:
            enricher.close()


def test_score_identity_conflict_gate_requires_valid_current_evidence(match_factory):
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    m = match_factory("conflict", "A", "B", "A")
    _known_score_identity_conflict(m, fetched_at=(now - timedelta(days=31)).isoformat())
    assert not recent_score_identity_conflict(m, now=now)
    m.provider_payload["_tbt_score"]["fetched_at"] = now.isoformat()
    assert recent_score_identity_conflict(m, now=now)
    m.provider_payload["_tbt_score"]["event_id"] = "999"
    assert not recent_score_identity_conflict(m, now=now)
    m.provider_payload["_tbt_score"]["event_id"] = "123"
    m.provider_payload["_tbt_event_identity"]["away"] = "B"
    assert not recent_score_identity_conflict(m, now=now)
    m.provider_payload["_tbt_event_identity"]["away"] = "X"
    m.provider_payload["_tbt_score"]["fetched_at"] = "bad"
    assert not recent_score_identity_conflict(m, now=now)


def test_expired_identity_mismatch_recheck_quarantines_without_hourly_refetch(
    match_factory, tmp_path,
):
    class Provider:
        calls = []
        def _get(self, path, **kwargs):
            self.calls.append(path)
            assert path == "/api/tennis/event/123"
            return {"event": {
                "homeTeam": {"id": "A"}, "awayTeam": {"id": "X"},
                "status": {"type": "finished"},
            }}

    now = datetime.now(timezone.utc)
    m = match_factory("conflict", "A", "B", "A")
    _known_score_identity_conflict(m, fetched_at=(now - timedelta(days=31)).isoformat())
    provider = Provider()
    enricher = StatisticsEnricher(provider, tmp_path/"retry.sqlite", targeted=True)
    try:
        assert enricher.enrich(m) == "conflict"
        assert provider.calls == ["/api/tennis/event/123"]
        assert m.provider_payload["_tbt_statistics"]["status"] == "conflict"
        assert m.provider_payload["_tbt_statistics"]["reason"] == "provider_identity_mismatch"
        assert not m.stats
        assert enricher.enrich(m) == "cached"
        assert provider.calls == ["/api/tennis/event/123"]
    finally:
        enricher.close()
