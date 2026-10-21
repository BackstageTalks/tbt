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


def test_active_shadow_capture_uses_completion_time_not_inference_start():
    """A model computed across kickoff cannot be relabeled as pre-match."""
    from datetime import datetime, timezone
    from test_shadow_evaluation import _prediction

    kickoff = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    started_at = kickoff - timedelta(minutes=3)
    inference_finished_at = kickoff + timedelta(minutes=1)
    prod = [_prediction("crossed-kickoff", kickoff, 0.67)]
    chal = [_prediction("crossed-kickoff", kickoff, 0.53)]
    arguments = dict(
        production_predictions=prod, challenger_predictions=chal,
        production_model_version="prod-v1",
        challenger_model_version="v7.2.1-capture-clock-test",
        completed_matches=[],
    )

    # Old behavior, passing inference-start timestamp, looks eligible.
    backdated = update_active_shadow([], **arguments, now=started_at)
    assert len(backdated) == 1

    # Correct behavior passes a fresh capture timestamp after inference.
    protected = update_active_shadow([], **arguments, now=inference_finished_at)
    assert protected == []


def test_active_shadow_preserves_exact_capture_clock_on_valid_fixture():
    from datetime import datetime, timezone
    from test_shadow_evaluation import _prediction

    kickoff = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    after_inference = kickoff - timedelta(minutes=20)
    prod = [_prediction("valid-fixture", kickoff, 0.67)]
    chal = [_prediction("valid-fixture", kickoff, 0.53)]
    captured = update_active_shadow(
        [], production_predictions=prod, challenger_predictions=chal,
        completed_matches=[], production_model_version="prod-v1",
        challenger_model_version="v7.2.1-capture-clock-test",
        now=after_inference,
    )
    assert len(captured) == 1
    assert captured[0]["captured_at"] == after_inference.isoformat()
    assert captured[0]["status"] == "pending"
