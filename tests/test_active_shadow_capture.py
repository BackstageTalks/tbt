from datetime import timedelta
from dataclasses import replace
from test_settle_frozen_721_shadow import fixture
from active_shadow_capture import update_active_shadow


def test_active_721_resolves_verified_alias_once_and_retains_711():
    now, payload, match = fixture()
    row = payload['rows'][0]
    duplicate = dict(row, match_id='later', captured_at=(now-timedelta(hours=4)).isoformat())
    legacy = dict(row, match_id='legacy', challenger_model_version='711')
    match = replace(match, match_id='canonical', provider_payload={
        '_tbt_provider_event_id': 'event1', '_tbt_event_identity': {
            'event_id': 'event1', 'home': 'a', 'away': 'b', 'status': 'finished'}})
    updated = update_active_shadow([legacy, row, duplicate], completed_matches=[match], now=now)
    by_id = {r['match_id']: r for r in updated}
    assert by_id['legacy'] == legacy
    assert by_id[row['match_id']]['status'] == 'settled'
    assert by_id[row['match_id']]['challenger_player1_probability'] == .71
    assert by_id['later']['status'] == 'excluded'
    assert by_id[row['match_id']]['settlement_identity']['canonical_match_id'] == 'canonical'
    assert update_active_shadow(updated, completed_matches=[match], now=now) == updated


def test_two_721_versions_of_same_event_are_separate_cohorts():
    now, payload, match = fixture()
    row = payload['rows'][0]
    new = dict(row, challenger_model_version='v7.2.1-next')
    result = update_active_shadow([row, new], completed_matches=[match], now=now)
    assert len(result) == 2
    assert all(r['status'] == 'settled' for r in result)
