from types import SimpleNamespace
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from inspect_champion_inputs import inspect


def test_inspects_training_variance_and_actual_nonleaf_splits():
    nodes=np.array([(False,1,3.),(True,0,0.)],dtype=[('is_leaf','?'),('feature_idx','i4'),('gain','f8')])
    model=SimpleNamespace(feature_names=['serve_quality_diff','elo_diff','weather_known'],
        excluded_features={'weather_known'},linear=SimpleNamespace(named_steps={
            'scale':SimpleNamespace(var_=np.array([0.,2.,0.]),n_samples_seen_=600),
            'model':SimpleNamespace(coef_=np.array([[0.,.7,0.]]))}),
        boost=SimpleNamespace(_predictors=[[SimpleNamespace(nodes=nodes)]]),
        version='test',metadata={},blend_weight=.8,elo_weight=.5)
    report=inspect(model)
    assert report['inputs'][0]['constant_during_training']
    assert not report['inputs'][0]['learned_linear_or_boost_effect']
    assert report['inputs'][1]['boost_split_count'] == 1
    assert report['inputs'][1]['boost_gain_sum'] == 3.
    assert report['inputs'][1]['learned_linear_or_boost_effect']
    assert not report['inputs'][2]['learned_linear_or_boost_effect']
