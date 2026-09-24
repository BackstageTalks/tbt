from datetime import timedelta
from types import SimpleNamespace

import pytest

import prepare_feed
from tbt.services import account_storage
from tbt.services.admin_storage import _FirestoreTableAdapter
from tbt.services.projection_odds import enrich_projection_odds
from test_account_inactivity import NOW, cfg, paid, setup, lifecycle


@pytest.mark.parametrize('days', [3, 7])
def test_notice_race_loser_does_not_send(monkeypatch, days):
    user = paid(days)
    sent, _, _, _ = setup(monkeypatch, [user])
    monkeypatch.setattr(lifecycle, 'save_subscription_notice_state', lambda *a, **k: {'notice_claimed': False})
    result = lifecycle.run_inactivity_review(cfg(), {}, now=NOW)
    assert not sent
    assert result[f'subscription_{days}'] == 0


@pytest.mark.parametrize('days', [3, 7])
def test_notice_rechecks_renewal(monkeypatch, days):
    user = paid(days)
    sent, _, saved, _ = setup(monkeypatch, [user])
    renewed = dict(user, app_metadata=dict(user['app_metadata'], blinq_expires_at=(NOW + timedelta(days=30)).isoformat()))
    monkeypatch.setattr(lifecycle, 'firebase_get_user', lambda *a: renewed)
    lifecycle.run_inactivity_review(cfg(), {}, now=NOW)
    assert not sent and not saved


@pytest.mark.parametrize('days', [3, 7])
def test_notice_explicit_failure_retryable_but_ambiguous_delivery_preserved(monkeypatch, days):
    user = paid(days)
    _, _, saved, _ = setup(monkeypatch, [user])
    monkeypatch.setattr(lifecycle, '_send_subscription_expiry', lambda *a, **k: False)
    result = lifecycle.run_inactivity_review(cfg(), {}, now=NOW)
    assert [x[1]['status'] for x in saved] == ['pending', 'failed']
    assert result['mail_failures'] == 1
    saved.clear()
    def ambiguous(*a, **k):
        raise TimeoutError('SMTP reply lost')
    monkeypatch.setattr(lifecycle, '_send_subscription_expiry', ambiguous)
    lifecycle.run_inactivity_review(cfg(), {}, now=NOW)
    assert [x[1]['status'] for x in saved] == ['pending']


@pytest.mark.parametrize('days', [3, 7])
def test_notice_storage_uses_conditional_claim_and_rejects_stale_worker(monkeypatch, days):
    class Entity(dict):
        metadata = {'etag': 'original-version'}
    row = Entity()
    calls = []
    def update(entity, **kw):
        calls.append(kw)
        row.update(entity)
    table = SimpleNamespace(get_entity=lambda **kw: row, update_entity=update)
    monkeypatch.setattr(account_storage, '_table', lambda name: table)
    args = dict(days=days, expires_for='2026-09-30T12:00:00+00:00', status='pending', pending_at=NOW.isoformat())
    assert account_storage.save_subscription_notice_state('u', **args)['notice_claimed']
    assert not account_storage.save_subscription_notice_state('u', **args)['notice_claimed']
    assert len(calls) == 1 and calls[0]['etag'] == 'original-version'
    assert calls[0]['match_condition'].name == 'IfNotModified'
    # A renewal is a distinct cycle, even if the old notice was pending.
    args['expires_for'] = '2026-10-30T12:00:00+00:00'
    assert account_storage.save_subscription_notice_state('u', **args)['notice_claimed']


@pytest.mark.parametrize('status', [409, 412])
def test_notice_claim_conflict_is_not_storage_failure(monkeypatch, status):
    class Conflict(Exception):
        status_code = status
    def conflict(**kw):
        raise Conflict()
    monkeypatch.setattr(account_storage, '_table', lambda name: SimpleNamespace(get_entity=conflict))
    assert account_storage.save_subscription_notice_state('u', days=7, expires_for='expiry', status='pending') == {'notice_claimed': False}


@pytest.mark.parametrize('race', [None, 'update', 'create'])
def test_firestore_notice_claim_preserves_version_and_handles_conflicts(monkeypatch, race):
    from google.api_core.exceptions import AlreadyExists, FailedPrecondition

    row = {'PartitionKey': 'account', 'RowKey': account_storage._key('u')}
    writes = []

    def update(entity, *, option):
        assert option._last_update_time == NOW
        if race == 'update':
            raise FailedPrecondition('Another worker updated the entity')
        writes.append(entity)
        row.update(entity)

    def create(entity):
        if race == 'create':
            raise AlreadyExists('Another worker created the entity')
        raise AssertionError('Existing metadata must use conditional update')

    document = SimpleNamespace(
        get=lambda: SimpleNamespace(exists=race != 'create', update_time=NOW, to_dict=lambda: dict(row)),
        update=update, create=create,
    )
    adapter = _FirestoreTableAdapter.__new__(_FirestoreTableAdapter)
    adapter._collection = SimpleNamespace(document=lambda key: document)
    monkeypatch.setattr(account_storage, '_table', lambda name: adapter)
    args = dict(days=7, expires_for='expiry', status='pending', pending_at=NOW.isoformat())
    result = account_storage.save_subscription_notice_state('u', **args)
    assert result['notice_claimed'] is (race is None)
    if race is None:
        assert not account_storage.save_subscription_notice_state('u', **args)['notice_claimed']
        assert len(writes) == 1


def test_photo_archive_recovers_missing_profile_and_nested_doubles():
    payload = {'markets': {'doubles': [{'player1': {'id': 'team', 'members': [{'id': '42'}]}, 'player2': {'id': '43'}}]}}
    assert {'42', '43'} <= prepare_feed._feed_player_ids(payload)
    prepare_feed._merge_player_profiles(payload, {}, {'42.webp', '43.jpg'})
    row = payload['markets']['doubles'][0]
    assert row['player1']['members'][0]['photo_url'] == '/assets/players/42.webp'
    assert row['player2']['photo_url'] == '/assets/players/43.jpg'
    assert 'photo_url' not in row['player1']


def test_aces_nested_market_metadata_prices_exact_selection_only():
    card = {'event_id': '1', 'market': 'aces', 'selection_id': 'b', 'player1': {'id': 'a', 'name': 'Alpha'}, 'player2': {'id': 'b', 'name': 'Beta'}}
    def payload(name):
        return {'markets': [{'market': {'name': name}, 'choices': [{'name': 'Alpha', 'decimalOdds': 1.8}, {'name': 'Beta', 'decimalOdds': 2.1}]}]}
    provider = SimpleNamespace(event_odds=lambda *a, **kw: payload('Most aces'))
    rows, _, report = enrich_projection_odds(provider, [card], [], max_events=1)
    assert rows[0]['odds'] == 2.1 and report['priced_cards']['aces'] == 1
    provider.event_odds = lambda *a, **kw: payload('First set most aces')
    rows, _, _ = enrich_projection_odds(provider, [card], [], max_events=1)
    assert 'odds' not in rows[0]
