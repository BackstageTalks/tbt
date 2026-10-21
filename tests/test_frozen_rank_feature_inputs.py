import hashlib
import io
import json
import tarfile
from unittest.mock import Mock

import pytest
import rank_feature_inputs as r
import guarded_candidate_backup as backup


def test_frozen_rank_inputs_never_redownload_changed_live_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, 'BASE', tmp_path)
    verify = Mock(return_value={})
    monkeypatch.setattr(backup, 'validate_certificate', verify)
    root = tmp_path / 'rank-feature-inputs'
    source = root / 'source'
    source.mkdir(parents=True)
    metadata = tmp_path / 'training-source-metadata'
    metadata.mkdir()
    manifest = {'downloaded': []}
    for tour, asset in (('atp', r.ATP_ASSET), ('wta', r.WTA_ASSET)):
        path = source / asset
        with tarfile.open(path, 'w:gz') as archive:
            for name in (f'{tour}_players.csv', f'{tour}_rankings_current.csv'):
                raw = b'id,name\n1,Player\n'
                entry = tarfile.TarInfo(name)
                entry.size = len(raw)
                archive.addfile(entry, io.BytesIO(raw))
        manifest['downloaded'].append({'asset': asset, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (metadata / 'rank_source_acquisition.json').write_text(json.dumps(manifest))
    supplement = source / r.Path(r.WTA_OFFICIAL_SUPPLEMENT_PATH).name
    supplement.write_bytes(b'frozen-supplement')
    (metadata / 'wta_supplement_audit.json').write_text(json.dumps({
        'singles': {'gzip_sha256': hashlib.sha256(supplement.read_bytes()).hexdigest()}}))
    (root / 'profiles').mkdir()
    (root / 'profiles/player_profiles.json').write_text('{"frozen":true}')
    for name in ('ReleaseStore', '_repo_json', '_source_manifest', '_download_repo_binary'):
        monkeypatch.setattr(r, name, Mock(side_effect=AssertionError('Live inputs must not be consulted')))
    def profiles(path):
        assert json.loads(path.read_text()) == {'frozen': True}
        return {}, {}
    monkeypatch.setattr(r, 'load_profiles', profiles)
    monkeypatch.setattr(r, 'build_canonical_players', lambda *a, **k: [])
    monkeypatch.setattr(r, 'load_sackmann_players', lambda *a: [])
    monkeypatch.setattr(r, 'build_crosswalk', lambda *a: ([], {}))
    monkeypatch.setattr(r, 'crosswalk_mapping', lambda *a: {})
    monkeypatch.setattr(r.ATPRankHistory, 'from_sackmann', lambda *a, **k: 'frozen-atp')
    monkeypatch.setattr(r.WTARankHistory, 'from_sackmann', lambda *a, **k: 'frozen-wta')
    result = r.load_rank_feature_inputs(backup.REPO, root, [], frozen=True)
    assert (result.atp, result.wta) == ('frozen-atp', 'frozen-wta')
    assert result.report['status'] == 'verified'
    verify.assert_called_once_with(require_writer_lock=False)


def test_frozen_ranking_rejects_uncertified_input_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, 'BASE', tmp_path)
    monkeypatch.setattr(backup, 'validate_certificate', Mock(side_effect=RuntimeError('Changed input')))
    with pytest.raises(RuntimeError, match='Changed input'):
        r.load_rank_feature_inputs(backup.REPO, tmp_path / 'rank-feature-inputs', [], frozen=True)
    with pytest.raises(ValueError, match='certified'):
        r.load_rank_feature_inputs(backup.REPO, tmp_path / 'other', [], frozen=True)
