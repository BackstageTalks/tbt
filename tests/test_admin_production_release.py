import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
import admin_production_release as p
from test_admin_model_lab import TestLab, snapshot
from tbt.services import model_lab as lab


class TestProductionQueue(TestLab):
    def payload(self):
        tag = snapshot()['candidates'][0]['tag']
        return dict(action='promote_production', source_tag=tag, calibration_override=True,
                    confirmation='RELEASE ' + tag, reason='Owner accepts incomplete calibration')

    def test_waiver_requires_explicit_confirmation(self):
        for key in ('confirmation', 'calibration_override', 'reason'):
            payload = self.payload()
            payload.pop(key)
            with pytest.raises(ValueError):
                lab.start(payload, 'owner')
        assert lab._json('active') is None

    def test_production_release_is_pinned_and_independently_verified(self):
        queued = lab.start(self.payload(), 'owner')
        request = lab.sync(snapshot())['pending']
        assert request['actor'] == 'owner'
        assert request['expected_champion_sha256'] == 'b' * 64
        assert request['source_sha256'] == 'c' * 64
        state = snapshot()
        state['runs']['promote_production'] = [dict(id=123, status='completed', conclusion='success',
            display_title='Model Lab production release ' + queued['id'], created_at=request['created_at'])]
        with pytest.raises(lab.TrainingBlocked):
            lab.sync(state)
        assert lab._json('active')
        state['champion_sha256'] = 'c' * 64
        lab.sync(state)
        assert lab._json('active') is None
        assert lab._json('last')['state'] == 'WORKFLOW_VERIFIED'


@pytest.fixture
def remote(tmp_path, monkeypatch):
    sha = lambda b: hashlib.sha256(b).hexdigest()
    tag = 'blinq-candidate-frozen-123-1'
    report = {'promotion_decision': {'candidate_version': 'new', 'production_version': 'old'},
              'evaluation_governance': {'holdout_fingerprint': 'test'}}
    bundle = lambda value: {'model.joblib': value, 'training_report.json': json.dumps(report).encode(), 'promotion_history.json': b'[]'}
    data = {tag: bundle(b'new'), p.PRODUCTION: bundle(b'old'),
            'tbt-champion-backup-sha256-' + sha(b'old'): bundle(b'old')}
    writes = []
    def download(tag, directory, names):
        directory.mkdir(parents=True, exist_ok=True)
        for k, v in data[tag].items():
            (directory / k).write_bytes(v)
        return SimpleNamespace(directory=directory), dict(data[tag])
    def publish(store, tag, files, readback):
        writes.append(tag)
        data[tag] = dict(files)
        download(tag, readback, tuple(files))
    monkeypatch.setattr(p, 'download', download)
    monkeypatch.setattr(p, 'checked_publish', publish)
    monkeypatch.setattr(p, 'verify_restore', Mock(return_value={'status': 'PASS'}))
    monkeypatch.setattr(p, 'verify_complete_bundle', Mock())
    monkeypatch.setattr(p, 'load_model', lambda path: SimpleNamespace(
        fitted=True, version=Path(path).read_text(), feature_names=['elo_probability'],
        predict_proba=lambda frame: [.4, .5, .6]))
    import cdb_global_writer_lock, release_store
    monkeypatch.setattr(cdb_global_writer_lock, 'verify', Mock())
    monkeypatch.setattr(release_store, '_run_gh', lambda args: SimpleNamespace(returncode=0))
    args = (tag, sha(b'new'), sha(b'old'), 'Owner release calibration waiver', 'a' * 24)
    return data, writes, args, tmp_path, publish


def test_waiver_records_release_and_verifies_rollback(remote):
    data, writes, args, path, _ = remote
    result = p.release(*args, override=True, cache=path)
    assert result['remote_readback'] == 'VERIFIED'
    assert result['quality_status'] == 'OPERATOR_WAIVED_NOT_VERIFIED'
    assert writes == [p.PRODUCTION]
    assert data[p.PRODUCTION]['model.joblib'] == b'new'
    assert json.loads(data[p.PRODUCTION]['promotion_history.json'])[-1]['calibration_override'] is True
    p.verify_restore.assert_called_once()


def test_stale_champion_or_missing_waiver_never_writes(remote):
    data, writes, args, path, _ = remote
    with pytest.raises(ValueError):
        p.release(*args, override=False, cache=path)
    data[p.PRODUCTION]['model.joblib'] = b'changed'
    with pytest.raises(ValueError, match='changed after'):
        p.release(*args, override=True, cache=path)
    assert writes == []


def test_backup_mismatch_blocks_before_publication(remote):
    data, writes, args, path, _ = remote
    data['tbt-champion-backup-sha256-' + args[2]]['training_report.json'] = b'{}'
    with pytest.raises(ValueError, match='rollback'):
        p.release(*args, override=True, cache=path)
    assert writes == []


def test_partial_publish_restores_exact_old_bundle(remote, monkeypatch):
    data, writes, args, path, publish = remote
    old = dict(data[p.PRODUCTION])
    def fail_once(store, tag, files, readback):
        publish(store, tag, files, readback)
        if len(writes) == 1:
            raise RuntimeError('Remote readback failed')
    monkeypatch.setattr(p, 'checked_publish', fail_once)
    with pytest.raises(RuntimeError, match='readback failed'):
        p.release(*args, override=True, cache=path)
    assert data[p.PRODUCTION] == old
    assert writes == [p.PRODUCTION, p.PRODUCTION]
    p.verify_complete_bundle.assert_called_once()


def test_restore_failure_blocks_before_publication(remote, monkeypatch):
    _, writes, args, path, _ = remote
    monkeypatch.setattr(p, 'verify_restore', Mock(side_effect=ValueError('restore parity failed')))
    with pytest.raises(ValueError, match='parity'):
        p.release(*args, override=True, cache=path)
    assert writes == []
