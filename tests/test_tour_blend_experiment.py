import numpy as np
import pytest
from tbt.models.tour_blend_experiment import compare_tour_blends


def inputs():
    rng = np.random.default_rng(721)
    n = 4000
    y = rng.integers(0, 2, n)
    tours = np.arange(n) % 2
    good = np.where(y, .9, .1)
    bad = 1-good
    return (np.where(tours, good, bad), np.where(tours, bad, good),
            np.full(n, .5), y, tours)


def test_different_tours_choose_different_models_and_improve_future_slice():
    r = compare_tour_blends(*inputs(), 2200, (.5, 0))
    assert r['tours']['atp']['weights']['linear'] == 1
    assert r['tours']['wta']['weights']['boost'] == 1
    for tour in r['tours'].values():
        assert tour['delta']['log_loss'] < 0
        assert tour['delta']['brier'] < 0
    assert r['serving_weights_changed'] is False
    assert r['holdout_used'] is False


def test_later_labels_cannot_choose_weights():
    data = inputs()
    original = compare_tour_blends(*data, 2200, (.5, 0))
    data[3][2200:] = 1-data[3][2200:]
    changed = compare_tour_blends(*data, 2200, (.5, 0))
    for tour in ('atp', 'wta'):
        assert changed['tours'][tour]['weights'] == original['tours'][tour]['weights']
        assert changed['tours'][tour]['delta']['log_loss'] > 0


def test_invalid_and_insufficient_data():
    data = inputs()
    data[4][:] = 1
    assert compare_tour_blends(*data, 2200, (.5, 0))['tours']['wta']['status'] == 'INSUFFICIENT_DATA'
    data[0][0] = np.nan
    with pytest.raises(ValueError):
        compare_tour_blends(*data, 2200, (.5, 0))
