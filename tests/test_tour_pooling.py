import numpy as np
import pandas as pd
import pytest

from tbt.models.tour_pooling import pooled_predictions


class Fixed:
    def __init__(self, p):
        self.p = p
        self.seen = []

    def predict_proba(self, frame):
        self.seen.extend(frame.key.tolist())
        return np.full(len(frame), self.p)


def test_routes_positionally_and_falls_back_without_cross_tour_calls():
    frame = pd.DataFrame({'tour_atp': [0, 1, 0, 1], 'key': ['a', 'b', 'c', 'd']}, index=[2, 2, 1, 1])
    shared, atp = Fixed(.6), Fixed(.8)
    result = pooled_predictions(frame, shared, {'atp': atp}, {'atp': .5})
    np.testing.assert_allclose(result, [.6, .7, .6, .7])
    assert atp.seen == ['b', 'd']
    assert shared.seen == ['a', 'b', 'c', 'd']


@pytest.mark.parametrize('weight', [-1, 1.1, float('nan'), float('inf'), True])
def test_invalid_weights_fail_closed(weight):
    frame = pd.DataFrame({'tour_atp': [1], 'key': ['a']})
    with pytest.raises(ValueError):
        pooled_predictions(frame, Fixed(.5), {'atp': Fixed(.8)}, {'atp': weight})


def test_missing_specialist_unknown_tour_and_invalid_prediction_fail():
    frame = pd.DataFrame({'tour_atp': [1], 'key': ['a']})
    with pytest.raises(ValueError):
        pooled_predictions(frame, Fixed(.5), {}, {'atp': .5})
    with pytest.raises(ValueError):
        pooled_predictions(frame.assign(tour_atp=np.nan), Fixed(.5), {}, {})
    with pytest.raises(ValueError):
        pooled_predictions(frame, Fixed(np.nan), {}, {})


def test_zero_weight_and_empty_frame_do_not_call_specialist():
    frame = pd.DataFrame({'tour_atp': [0], 'key': ['a']})
    bad = Fixed(np.nan)
    np.testing.assert_allclose(pooled_predictions(frame, Fixed(.4), {'wta': bad}, {'wta': 0}), [.4])
    assert not bad.seen
    assert pooled_predictions(frame.iloc[:0], bad, {}, {}).size == 0
