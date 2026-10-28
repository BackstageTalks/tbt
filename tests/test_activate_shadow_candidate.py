import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import activate_shadow_candidate as a


@pytest.fixture
def remote(tmp_path, monkeypatch):
    source = 'blinq-candidate-frozen-123-1'
    version = 'v7.2.1-new'
    report = {'promotion_decision': {'candidate_version': version, 'production_version': 'champ',
                                    'promotion_requested': False},
              'evaluation_governance': {'holdout_fingerprint': 'held-out'},
              'holdout': {'n': 300}, 'production_holdout': {'n': 300}}
    def bundle(model):
        return {'model.joblib': model, 'training_report.json': json.dumps(report).encode(),
                'promotion_history.json': b'[]'}
    old_rows = [{'match_id': 'old', 'challenger_model_version': '711',
                 'production_model_version': 'champ', 'status': 'pending'}]
    data = {source: bundle(b'new'), a.CANDIDATE: bundle(b'old'), a.PRODUCTION: bundle(b'champ'),
            a.SHADOW: {'shadow_ledger.json': json.dumps(old_rows).encode(), 'shadow_report.json': b'{}'}}
    writes = []
    class Store:
        def __init__(self, repo, tag, directory):
            self.tag, self.directory = tag, directory
            directory.mkdir(parents=True, exist_ok=True)
        def download(self, **kw):
            assert kw['require_bundle_manifest'] is True
            for name in kw['required_names']:
                (self.directory / name).write_bytes(data[self.tag][name])
        def upload_bundle(self, paths):
            writes.append(self.tag)
            assert self.tag != a.PRODUCTION
            data[self.tag] = {p.name: p.read_bytes() for p in paths}
    monkeypatch.setattr(a, 'ReleaseStore', Store)
    monkeypatch.setattr(a, 'load_model', lambda path: SimpleNamespace(
        fitted=True, version={'new': version, 'champ': 'champ'}[__import__('pathlib').Path(path).read_text()]))
    import cdb_global_writer_lock, release_store
    monkeypatch.setattr(cdb_global_writer_lock, 'verify', Mock())
    monkeypatch.setattr(release_store, '_run_gh', lambda args: SimpleNamespace(returncode=0))
    return source, data, writes, tmp_path, hashlib.sha256(b'old').hexdigest()


def test_activation_preserves_history_and_production_and_reads_back(remote):
    tag, data, writes, path, expected = remote
    old_rows = data[a.SHADOW]['shadow_ledger.json']
    result = a.activate(tag, expected, cache=path)
    assert result['remote_readback'] == 'VERIFIED'
    assert data[a.CANDIDATE] == data[tag]
    assert data[a.SHADOW]['shadow_ledger.json'] == old_rows
    assert data[a.PRODUCTION]['model.joblib'] == b'champ'
    assert writes == [a.CANDIDATE, a.SHADOW]
    report = json.loads(data[a.SHADOW]['shadow_report.json'])
    assert report['challenger_model_version'] == 'v7.2.1-new'
    assert report['cohort']['captured'] == 0
    assert report['gate']['automatic_promotion'] is False
    # Repeating an already successful request is safe.
    assert a.activate(tag, expected, cache=path / 'retry')['remote_readback'] == 'VERIFIED'


def test_stale_candidate_fails_before_write(remote):
    tag, data, writes, path, expected = remote
    data[a.CANDIDATE]['model.joblib'] = b'other-run'
    with pytest.raises(ValueError, match='Candidate changed'):
        a.activate(tag, expected, cache=path)
    assert writes == []


def test_failed_shadow_readback_restores_both_bundles(remote, monkeypatch):
    tag, data, writes, path, expected = remote
    saved = {k: dict(v) for k, v in data.items()}
    original = a.download
    def download(tag, directory, names):
        result = original(tag, directory, names)
        if directory.name == 'shadow-readback':
            raise RuntimeError('simulated readback failure')
        return result
    monkeypatch.setattr(a, 'download', download)
    with pytest.raises(RuntimeError, match='simulated'):
        a.activate(tag, expected, cache=path)
    assert data == saved
    assert writes == [a.CANDIDATE, a.SHADOW, a.CANDIDATE, a.SHADOW]


def test_wrong_champion_fails_before_write(remote):
    tag, data, writes, path, expected = remote
    report = json.loads(data[tag]['training_report.json'])
    report['promotion_decision']['production_version'] = 'different'
    data[tag]['training_report.json'] = json.dumps(report).encode()
    with pytest.raises(ValueError, match='provenance'):
        a.activate(tag, expected, cache=path)
    assert writes == []


def test_existing_probabilities_never_overwritten():
    row = {'match_id': 'x', 'production_model_version': 'p', 'challenger_model_version': 'c',
           'challenger_player1_probability': .7}
    with pytest.raises(ValueError, match='Conflicting'):
        a.combine_rows([row], [row | {'challenger_player1_probability': .8}])
    assert a.combine_rows([row], [row]) == [row]


def test_prospective_research_requires_exact_hash_and_provenance(remote, monkeypatch):
    tag, data, writes, path, expected = remote
    report = json.loads(data[tag]['training_report.json'])
    report['promotion_decision']['candidate_version'] = 'v7.2.2-new'
    original_load = a.load_model
    def load(path):
        model = original_load(path)
        if model.version == 'v7.2.1-new':
            model.version = 'v7.2.2-new'
        return model
    monkeypatch.setattr(a, 'load_model', load)
    report.update(holdout={}, production_holdout={}, evaluation_governance={},
                  immutable_training_backup={'tag': tag.replace('candidate-frozen', 'full-training-backup'),
                      'candidate_tag': tag, 'asset_count': 99,
                      'champion_sha256': hashlib.sha256(b'champ').hexdigest()})
    data[tag]['training_report.json'] = json.dumps(report).encode()
    with pytest.raises(ValueError, match='holdout'):
        a.activate(tag, expected, cache=path)
    with pytest.raises(ValueError, match='exact source'):
        a.activate(tag, expected, cache=path, prospective_only=True, expected_source_sha='0'*64)
    assert not writes
    result = a.activate(tag, expected, cache=path, prospective_only=True,
                        expected_source_sha=hashlib.sha256(b'new').hexdigest())
    assert result['remote_readback'] == 'VERIFIED'
    shadow = json.loads(data[a.SHADOW]['shadow_report.json'])
    assert shadow['candidate_activation']['quality_status'] == 'UNVERIFIED_RESEARCH'
    assert shadow['candidate_activation']['imported_prospective_rows'] == 0
    assert shadow['gate']['automatic_promotion'] is False
    assert data[a.PRODUCTION]['model.joblib'] == b'champ'


def test_prospective_backup_mismatch_never_writes(remote):
    tag, data, writes, path, expected = remote
    with pytest.raises(ValueError, match='backup provenance'):
        a.activate(tag, expected, cache=path, prospective_only=True,
                   expected_source_sha=hashlib.sha256(b'new').hexdigest())
    assert not writes
