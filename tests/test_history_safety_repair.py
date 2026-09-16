from dataclasses import replace

from tbt.data.history_safety import sanitize_history_identities
from tbt.services.data_quality import audit_history


def test_history_safety_merges_proven_duplicate_provider_event(match_factory):
    a = match_factory('a', 'A', 'B', 'A')
    a.provider_payload = {'_tbt_provider_event_id': '777'}
    b = replace(a, match_id='legacy-other-id')
    b.provider_payload = {'_tbt_provider_event_id': '777'}
    safe, report = sanitize_history_identities([a, b])
    assert len(safe) == 1
    assert report['merged_rows_removed'] == 1
    assert report['quarantined_rows'] == 0
    accepted, _ = audit_history(safe, now=a.scheduled_at.replace(year=a.scheduled_at.year + 1))
    assert len(accepted) == 1


def test_history_safety_quarantines_unresolved_identity_collision(match_factory):
    a = match_factory('collision', 'A', 'B', 'A')
    a.provider_payload = {'_tbt_provider_event_id': '101'}
    b = replace(a)
    b.provider_payload = {'_tbt_provider_event_id': '202'}
    safe, report = sanitize_history_identities([a, b])
    assert safe == []
    assert report['quarantined_rows'] == 2
    assert report['duplicate_match_ids'] == ['collision']


def test_strict_audit_still_fails_closed_without_safety_layer(match_factory):
    a = match_factory('a', 'A', 'B', 'A')
    a.provider_payload = {'id': '123'}
    b = replace(a, match_id='other')
    import pytest
    with pytest.raises(ValueError, match='Duplicate'):
        audit_history([a, b], now=a.scheduled_at.replace(year=a.scheduled_at.year + 1))


def test_incoming_collision_is_quarantined_without_evicting_existing(match_factory):
    from tbt.data.history_safety import merge_trusted_history_batch

    existing = match_factory('collision', 'A', 'B', 'A')
    existing.provider_payload = {'_tbt_provider_event_id': '101'}
    incoming = replace(existing)
    incoming.provider_payload = {'_tbt_provider_event_id': '202'}

    safe, accepted, report = merge_trusted_history_batch([existing], [incoming])
    assert len(safe) == 1
    assert safe[0].provider_payload['_tbt_provider_event_id'] == '101'
    assert accepted == []
    assert report['quarantined_rows'] == 1


def test_incoming_provider_id_collision_with_other_players_is_quarantined(match_factory):
    from tbt.data.history_safety import merge_trusted_history_batch

    existing = match_factory('known', 'A', 'B', 'A')
    existing.provider_payload = {'_tbt_provider_event_id': '777'}
    incoming = match_factory('other', 'C', 'D', 'C')
    incoming.provider_payload = {'_tbt_provider_event_id': '777'}

    safe, accepted, report = merge_trusted_history_batch([existing], [incoming])
    assert [m.match_id for m in safe] == ['known']
    assert accepted == []
    assert report['quarantined_rows'] == 1
    assert report['collision']['duplicate_provider_event_ids'] == ['777']


def test_history_safety_reports_only_changed_years(match_factory):
    from tbt.data.history_safety import sanitize_history_identities

    clean = match_factory('clean', 'C', 'D', 'C')
    clean = replace(clean, scheduled_at=clean.scheduled_at.replace(year=2024))
    a = match_factory('dup', 'A', 'B', 'A')
    a.provider_payload = {'_tbt_provider_event_id': '101'}
    b = replace(a)
    b.provider_payload = {'_tbt_provider_event_id': '202'}

    safe, report = sanitize_history_identities([clean, a, b])
    assert [m.match_id for m in safe] == ['clean']
    assert report['affected_years'] == [2025]


def test_quarantine_budget_is_bounded():
    from tbt.data.history_safety import quarantine_budget

    assert quarantine_budget(10) == 20
    assert quarantine_budget(500_000) == 500
