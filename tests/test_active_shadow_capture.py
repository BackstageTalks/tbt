import pytest
from datetime import timedelta
from dataclasses import replace
from test_settle_frozen_721_shadow import fixture
from active_shadow_capture import update_active_shadow


@pytest.mark.parametrize("version", ["v7.2.1-test", "v7.2.2-test"])
def test_active_721_resolves_verified_alias_once_and_retains_711(version):
    now, payload, match = fixture()
    row = dict(payload['rows'][0], challenger_model_version=version)
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


def test_pipeline_passes_wall_clock_after_challenger_inference():
    """Wiring regression: the capture guard must never receive prediction_now."""
    import ast
    from pathlib import Path

    pipeline = ast.parse(
        (Path(__file__).resolve().parents[1] / "scripts" / "pipeline.py")
        .read_text(encoding="utf-8")
    )
    assignments = [
        node for node in ast.walk(pipeline)
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "shadow_capture_now"
            for target in node.targets
        )
    ]
    updates = [
        node for node in ast.walk(pipeline)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "update_active_shadow"
    ]
    assert len(assignments) == len(updates) == 1
    assign = assignments[0]
    assert isinstance(assign.value, ast.Call)
    assert isinstance(assign.value.func, ast.Attribute)
    assert assign.value.func.attr == "now"
    assert isinstance(assign.value.func.value, ast.Name)
    assert assign.value.func.value.id == "datetime"
    assert assign.lineno < updates[0].lineno
    now = next(keyword.value for keyword in updates[0].keywords if keyword.arg == "now")
    assert isinstance(now, ast.Name) and now.id == "shadow_capture_now"



def test_new_provider_event_identity_collision_is_quarantined_without_rewriting_prior(capsys):
    """A reused native event ID must not stop daily publication or settle twice."""
    from copy import deepcopy
    from datetime import datetime, timezone
    from test_shadow_evaluation import _prediction

    now, payload, _ = fixture()
    original = deepcopy(payload['rows'])
    old = original[0]
    scheduled = now + timedelta(hours=6)
    new = _prediction('new-provider-collision', scheduled, .67,
                      p1_id='foreign-a', p2_id='foreign-b')
    new['event_id'] = old['event_id']
    challenger = deepcopy(new)
    challenger['player1']['probability'] = .73
    fresh = _prediction('valid-independent', scheduled, .67)
    good_challenger = deepcopy(fresh)
    good_challenger['player1']['probability'] = .71

    args = dict(
        production_predictions=[new, fresh],
        challenger_predictions=[challenger, good_challenger],
        completed_matches=[],
        production_model_version=old['production_model_version'],
        challenger_model_version=old['challenger_model_version'],
        now=now,
    )
    updated = update_active_shadow(original, **args)
    by_id = {r['match_id']: r for r in updated}
    assert by_id[old['match_id']] == old
    assert by_id['valid-independent']['status'] == 'pending'
    assert 'new-provider-collision' not in by_id
    assert original == payload['rows']  # no in-place mutation
    assert 'new_shadow_provider_identity_quarantined' in capsys.readouterr().out
    assert update_active_shadow(updated, **args) == updated


def test_two_new_incompatible_identities_for_one_event_are_both_rejected(capsys):
    from copy import deepcopy
    from datetime import datetime, timezone
    from test_shadow_evaluation import _prediction

    now = datetime(2026, 11, 5, 8, tzinfo=timezone.utc)
    scheduled = now + timedelta(hours=5)
    prod_a = _prediction('new-a', scheduled, .6, p1_id='a', p2_id='b')
    prod_b = _prediction('new-b', scheduled, .6, p1_id='c', p2_id='d')
    prod_a['event_id'] = prod_b['event_id'] = 'provider-reused'
    challenger = [deepcopy(prod_a), deepcopy(prod_b)]
    updated = update_active_shadow(
        [], production_predictions=[prod_a, prod_b],
        challenger_predictions=challenger, completed_matches=[],
        production_model_version='champion', challenger_model_version='v7.2.1-test',
        now=now,
    )
    assert updated == []
    assert '"conflicting_events": 1' in capsys.readouterr().out


def test_preexisting_conflicting_provider_event_id_still_fails_closed():
    from copy import deepcopy
    now, payload, _ = fixture()
    original = deepcopy(payload['rows'])
    collision = dict(original[0], match_id='prior-collision', player2_id='foreign')
    with pytest.raises(ValueError, match='Conflicting provider event identities'):
        update_active_shadow([*original, collision], completed_matches=[], now=now)
    assert original == payload['rows']


def test_same_native_id_in_different_model_pairs_is_not_false_collision():
    from copy import deepcopy
    from datetime import datetime, timezone
    from test_shadow_evaluation import _prediction

    now = datetime(2026, 11, 5, 8, tzinfo=timezone.utc)
    scheduled = now + timedelta(hours=5)
    prod = _prediction('new-722', scheduled, .64, p1_id='different', p2_id='players')
    prod['event_id'] = 'shared-id'
    existing = {
        'match_id': 'prior-721', 'event_id': 'shared-id', 'tour': 'ATP',
        'player1_id': 'a', 'player2_id': 'b',
        'captured_at': (now-timedelta(hours=1)).isoformat(),
        'scheduled_at': scheduled.isoformat(),
        'production_model_version': 'champion',
        'challenger_model_version': 'v7.2.1-test',
        'status': 'pending',
    }
    result = update_active_shadow(
        [existing], production_predictions=[prod],
        challenger_predictions=[deepcopy(prod)], completed_matches=[],
        production_model_version='champion', challenger_model_version='v7.2.2-test',
        now=now,
    )
    assert {x['match_id'] for x in result} == {'prior-721', 'new-722'}
