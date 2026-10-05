import hashlib
import json
import pytest
from audit_table_market import download_verified_year,aligned_event
from release_store import ReleaseStore
from tbt.models.feature_builder import FeatureBuilder


def test_scoped_partition_remains_fail_closed_on_corruption(tmp_path):
    raw=b'fake checked partition'
    digest=hashlib.sha256(raw).hexdigest()
    manifest=json.dumps({'years':{'2026':{'asset':'history-2026.parquet','sha256':digest,'rows':1}}}).encode()
    bundle=json.dumps({'files':{'history-2026.parquet':{'sha256':digest},'history_manifest.json':{'sha256':hashlib.sha256(manifest).hexdigest()}}}).encode()
    class Store:
        BUNDLE_MANIFEST=ReleaseStore.BUNDLE_MANIFEST
        directory=tmp_path
        corrupt=False
        def _asset_names(self):return {'history-2026.parquet','history_manifest.json',self.BUNDLE_MANIFEST,'history-2010.parquet'}
        def _download_asset(self,name):
            payload={self.BUNDLE_MANIFEST:bundle,'history_manifest.json':manifest,'history-2026.parquet':raw}[name]
            if self.corrupt and name=='history-2026.parquet':payload=b'changed during writer upload'
            (tmp_path/name).write_bytes(payload)
        _sha256=staticmethod(ReleaseStore._sha256)
    store=Store();assert download_verified_year(store,2026)[2]['rows']==1
    store.corrupt=True
    with pytest.raises(ValueError,match='checksum mismatch'):download_verified_year(store,2026)


def test_two_snapshots_require_identical_target_timestamp_surface_and_tour(match_factory):
    match=match_factory('stable-event','A','B','A',day=3)
    _,target=FeatureBuilder.orient_for_training(match)
    row={'target':target,'scheduled_at':match.scheduled_at,'surface':match.surface,'tour':match.tour}
    assert aligned_event(row,match)
    assert not aligned_event({**row,'target':1-target},match)
    assert not aligned_event({**row,'surface':'different'},match)
