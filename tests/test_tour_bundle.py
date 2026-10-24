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

def test_portable_bundle_json_roundtrip_matches_native():
    import json
    import math
    from types import SimpleNamespace as NS
    from tbt.models.ensemble import ProbabilityCalibrator
    from tbt.models.portable_model import predict_probability
    def component(p):
        m = FakeComponent(p)
        logit = math.log(p/(1-p))
        m.linear = NS(named_steps={'scale': NS(mean_=np.array([0.]), scale_=np.array([1.])),
            'model': NS(classes_=np.array([0,1]), coef_=np.array([[0.]]), intercept_=np.array([logit]))})
        node = {'value': 0., 'feature_idx': 0, 'num_threshold': 0.,
                'missing_go_to_left': True, 'left': 0, 'right': 0, 'is_leaf': True}
        m.boost = NS(_predictors=[[NS(nodes=[node])]], _baseline_prediction=np.array([[logit]]))
        m.calibrator = ProbabilityCalibrator()
        return m
    model = TourBundle(component(.6), {'atp': component(.8), 'wta': component(.4)},
                       {'atp': .5, 'wta': .25}, version='synthetic-parity')
    frame = pd.DataFrame({'tour_atp': [1,0,1,0]}, index=[1,1,0,0])
    portable = json.loads(json.dumps(export_portable_model(model), allow_nan=False))
    actual = [predict_probability(portable, row) for row in frame.to_dict('records')]
    np.testing.assert_allclose(actual, model.predict_proba(frame), atol=1e-12)
    portable['weights']['atp'] = float('nan')
    with pytest.raises(ValueError, match='weight'):
        predict_probability(portable, {'tour_atp': 0})
