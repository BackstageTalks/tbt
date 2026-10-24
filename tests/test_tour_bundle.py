import numpy as np
import pandas as pd
import pytest
from tbt.models.ensemble import TennisEnsemble
from tbt.models.tour_bundle import TourBundle
from tbt.models.artifact import save_model, load_model
from tbt.models.portable_export import export_portable_model


class FakeComponent(TennisEnsemble):
    def __init__(self, p):
        self.p = p
        self.fitted = True
        self.version = 'fake-test-component'
        self.feature_names = ['tour_atp']
        self.metadata = {}

    def predict_proba(self, frame):
        return np.full(len(frame), self.p)


def test_bundle_roundtrip_and_owned_components(tmp_path):
    pooled = FakeComponent(.6)
    model = TourBundle(pooled, {'atp': FakeComponent(.8)}, {'atp': .5}, version='test-bundle')
    pooled.p = .1  # Assembly owns its components.
    frame = pd.DataFrame({'tour_atp': [1, 0, 1]}, index=[2, 2, 1])
    path = str(tmp_path/'bundle.joblib')
    save_model(model, path)
    restored = load_model(path)
    np.testing.assert_allclose(restored.predict_proba(frame), [.7, .6, .7])
    assert restored.version == 'test-bundle'
    with pytest.raises(ValueError, match='partial export'):
        export_portable_model(restored)
    with pytest.raises(RuntimeError, match='governed'):
        restored.fit(frame, frame)


def test_bundle_rejects_schema_mismatch_and_unfitted_components():
    wrong = FakeComponent(.7)
    wrong.feature_names = ['different']
    with pytest.raises(ValueError, match='Incompatible'):
        TourBundle(FakeComponent(.6), {'wta': wrong}, {'wta': .5}, version='test')
    wrong.feature_names = ['tour_atp']
    wrong.fitted = False
    with pytest.raises(ValueError, match='unfitted'):
        TourBundle(FakeComponent(.6), {'wta': wrong}, {'wta': .5}, version='test')
