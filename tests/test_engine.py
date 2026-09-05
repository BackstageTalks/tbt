from datetime import datetime, timedelta, timezone
from dataclasses import replace
from types import SimpleNamespace
import copy

import numpy as np
import pytest
import httpx

from tbt.services.engine import predict, reconcile_ledger, serving_feed
from tbt.services.data_quality import audit_history
from tbt.services.auth import verify_user, AuthUnavailable
from tbt.services.feed import visible_feed, empty_feed


def test_prediction_is_frozen_and_settles_against_player_identity(match_factory):
    now = datetime(2025, 1, 2, tzinfo=timezone.utc)
    fixture = match_factory('future', 'A', 'B', None, day=3)
    fixture.provider_payload = {'id': '123'}
    model = SimpleNamespace(version='test', predict_proba=lambda frame: np.full(len(frame), .7))
    first = predict(model, [], [fixture], now)
    ledger = reconcile_ledger([], first, [], now)
    changed = copy.deepcopy(first)
    changed[0]['player1']['probability'] = .1
    changed[0]['scheduled_at'] = (fixture.scheduled_at + timedelta(days=1)).isoformat()
    ledger = reconcile_ledger(ledger, changed, [], now)
    assert ledger[0]['player1']['probability'] == .7
    assert ledger[0]['scheduled_at'] == changed[0]['scheduled_at']
    completed = replace(fixture.swapped(), winner_id='A')
    settled = reconcile_ledger(ledger, [], [completed], now + timedelta(days=3))
    assert settled[0]['result']['correct'] is True
    feed = serving_feed(settled, model, [completed], {}, [], now + timedelta(days=3))
    assert feed['performance']['n'] == 1
    assert feed['performance']['accuracy'] == 1


def test_no_same_day_results_enter_serving_features(match_factory):
    now = datetime(2025, 1, 2, tzinfo=timezone.utc)
    fixture = match_factory('future', 'A', 'B', None, day=3)
    history = [match_factory('past', 'A', 'B', 'A', day=2)]
    def probabilities(frame):
        assert frame.iloc[0]['data_depth'] == 0
        return [.5]
    predict(SimpleNamespace(version='test', predict_proba=probabilities), history, [fixture], now)


def test_duplicate_provider_event_stops_training(match_factory):
    a = match_factory('a', 'A', 'B', 'A')
    a.provider_payload = {'id': 123}
    b = replace(a, match_id='different-round-id')
    with pytest.raises(ValueError, match='Duplicate'):
        audit_history([a, b])


def test_auth_rejects_expired_and_unavailable_identity_service():
    cfg = SimpleNamespace(supabase_url='https://test.supabase.co', supabase_anon_key='public')
    assert verify_user(None, cfg) is None
    for status in (401, 403):
        with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(status))) as client:
            assert verify_user('Bearer expired', cfg, client) is None
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(500))) as client:
        with pytest.raises(AuthUnavailable):
            verify_user('Bearer anything', cfg, client)


def test_stale_feed_and_started_matches_are_explicit():
    now = datetime(2025, 1, 2, tzinfo=timezone.utc)
    data = empty_feed()
    data['generated_at'] = (now - timedelta(hours=13)).isoformat()
    data['upcoming'] = [{'scheduled_at': (now - timedelta(seconds=1)).isoformat()},
                        {'scheduled_at': (now + timedelta(hours=1)).isoformat()}]
    visible = visible_feed(data, now)
    assert visible['stale'] is True
    assert len(visible['upcoming']) == 1
