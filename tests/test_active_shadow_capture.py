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


@pytest.mark.parametrize("version", ["v7.2.1-test", "v7.2.2-test"])
def test_conflicting_provider_identity_excluded_without_settlement(version):
    """Ambiguous provider ID must not be scored, settled or silently merged."""
    from copy import deepcopy
    from tbt.services.frozen_721_research import exclude_repeated_events

    now, payload, match = fixture()
    original = dict(payload["rows"][0], challenger_model_version=version)
    collision = dict(original, match_id="different-fixture", player2_id="other")
    rows = [original, collision]
    untouched = deepcopy(rows)

    # Strict frozen research continues to fail closed on the same records.
    with pytest.raises(ValueError, match="Conflicting provider event identities"):
        exclude_repeated_events(rows)

    updated = update_active_shadow(rows, completed_matches=[match], now=now)
    assert rows == untouched
    assert {r["match_id"] for r in updated} == {
        original["match_id"], collision["match_id"]
    }
    assert all(r["event_id"] == "event1" for r in updated)
    assert all(r["status"] == "excluded" for r in updated)
    assert all(r["excluded_reason"] == "conflicting_provider_event_identity"
               for r in updated)
    assert all(r["shadow_status_before_quarantine"] == "pending"
               for r in updated)
    assert not any(r.get("target_player1_win") is not None for r in updated)
    assert update_active_shadow(updated, completed_matches=[match], now=now) == updated


def test_conflicting_previously_settled_shadow_identity_removed_from_scoring():
    now, payload, match = fixture()
    settled = dict(payload["rows"][0], status="settled", target_player1_win=1)
    collision = dict(payload["rows"][0], match_id="reused-event-other-players",
                     player1_id="other")
    updated = update_active_shadow([settled, collision], completed_matches=[match], now=now)
    assert len(updated) == 2
    assert all(r["status"] == "excluded" for r in updated)
    assert next(r for r in updated if r["match_id"] == settled["match_id"])[
        "shadow_status_before_quarantine"
    ] == "settled"


def test_pipeline_shields_production_from_active_shadow_errors():
    """Shadow prediction, update, report and upload must share one exception guard."""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "scripts" / "pipeline.py"
              ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    shadow_tries = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        and any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "update_active_shadow"
            for statement in node.body for n in ast.walk(statement)
        )
        and any(
            isinstance(handler.type, ast.Name)
            and handler.type.id == "Exception"
            for handler in node.handlers
        )
    ]
    assert len(shadow_tries) == 1
    shield = shadow_tries[0]
    assert any(isinstance(h.type, ast.Name) and h.type.id == "Exception"
               for h in shield.handlers)
    calls = [
        n for n in ast.walk(shield)
        if isinstance(n, ast.Call)
    ]
    assert any(isinstance(n.func, ast.Name) and n.func.id == "build_shadow_report"
               for n in calls)
    assert any(isinstance(n.func, ast.Attribute)
               and n.func.attr == "upload_bundle"
               for n in calls)
    assert "active_shadow_evaluation_unavailable" in source
    assert "production_refresh_continues" in source
