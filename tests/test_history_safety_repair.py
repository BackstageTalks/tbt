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

def test_preexisting_canonical_provider_collision_survives_unrelated_history_import(match_factory):
    """2026 ITF provider-ID collision must not delete either historical row."""
    from dataclasses import replace
    from datetime import datetime, timezone
    from tbt.data.history_safety import merge_trusted_history_batch

    first = match_factory("itf-one", "A", "B", "A", tour="atp")
    second = match_factory("itf-two", "C", "D", "C", tour="atp")
    first.provider_payload = {"_tbt_provider_event_id": "2026-ambiguous"}
    second.provider_payload = {"_tbt_provider_event_id": "2026-ambiguous"}
    later = replace(first, scheduled_at=datetime(2026, 10, 26, tzinfo=timezone.utc))
    first = later
    second = replace(second, scheduled_at=later.scheduled_at)
    wimbledon = match_factory("wimbledon-2016", "Serena", "Kerber", "Serena", tour="wta")
    wimbledon = replace(wimbledon, scheduled_at=datetime(2016, 7, 9, tzinfo=timezone.utc))
    wimbledon.provider_payload = {"_tbt_provider_event_id": "7115726"}

    result, accepted, report = merge_trusted_history_batch(
        [first, second], [wimbledon]
    )
    assert len(result) == 3
    assert [m.match_id for m in result if m.scheduled_at.year == 2026] == [
        "itf-one", "itf-two"
    ]
    assert [m.match_id for m in accepted] == ["wimbledon-2016"]
    assert report["protected_existing_rows"] == 2
    assert report["protected_existing_provider_id_collisions"] == 1
    assert report["quarantined_rows"] == 0


def test_conflicting_new_native_event_is_quarantined_without_2026_row_loss(match_factory):
    from dataclasses import replace
    from tbt.data.history_safety import merge_trusted_history_batch

    old1 = match_factory("old-1", "A", "B", "A")
    old2 = match_factory("old-2", "C", "D", "C")
    old1.provider_payload = {"_tbt_provider_event_id": "native-conflict"}
    old2.provider_payload = {"_tbt_provider_event_id": "native-conflict"}
    incoming = match_factory("new", "E", "F", "E")
    incoming.provider_payload = {"_tbt_provider_event_id": "native-conflict"}
    result, accepted, report = merge_trusted_history_batch(
        [old1, old2], [incoming]
    )
    assert [m.match_id for m in result] == ["old-1", "old-2"]
    assert accepted == []
    assert report["quarantined_rows"] == 1
    assert report["protected_existing_rows"] == 2
    assert report["rows"][0]["reason"] == "incoming_hits_preexisting_cdb_identity_quarantine"
