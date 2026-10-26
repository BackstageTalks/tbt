import numpy as np
import pytest
from tbt.models.accuracy_blend import select_accuracy_blend


def sample():
    y = (np.arange(1600) % 2).astype(float)
    tours = ((np.arange(1600) // 2) % 2).astype(float)
    good = np.where(y == 1, .8, .2)
    weak = np.where(y == 1, .6, .4)
    weak[np.arange(1600) % 5 == 0] = 1 - weak[np.arange(1600) % 5 == 0]
    return weak, good, np.full(1600, .5), y, tours


def test_accuracy_improvement_requires_later_tour_validation():
    selected, evidence = select_accuracy_blend(*sample(), 900, (0., 0.))
    assert selected is not None
    assert evidence['status'] == 'ACCEPTED'
    assert evidence['holdout_used'] is False
    for group in evidence['validation'].values():
        assert group['candidate']['accuracy'] > group['baseline']['accuracy']
        assert group['candidate']['log_loss'] < group['baseline']['log_loss']


def test_later_labels_can_reject_but_cannot_choose_different_weights():
    args = sample()
    _, before = select_accuracy_blend(*args, 900, (0., 0.))
    args[3][900:] = 1 - args[3][900:]
    selected, after = select_accuracy_blend(*args, 900, (0., 0.))
    assert selected is None
    assert after['selected_on_early_slice'] == before['selected_on_early_slice']
    assert after['status'] == 'BASELINE_RETAINED'


def test_absent_tour_does_not_allow_unverified_specialization():
    args = sample()
    args[4][:] = 1
    selected, evidence = select_accuracy_blend(*args, 900, (0., 0.))
    assert selected is None
    assert evidence['status'] == 'INSUFFICIENT_DATA'


def test_nonfinite_inputs_fail_closed():
    args = sample()
    args[0][0] = np.nan
    with pytest.raises(ValueError):
        select_accuracy_blend(*args, 900, (0., 0.))


def test_worker_passes_722_and_shadow_opt_in_to_existing_workflow(monkeypatch):
    import admin_training_worker as worker
    state = {"can_start": True, "base": "123"}
    monkeypatch.setattr(worker, 'collect_status', lambda: state)
    monkeypatch.setattr(worker, 'inspect', lambda: state)
    monkeypatch.setattr(worker, 'sync', lambda *a, **k: {
        "pending": {"profile": "accuracy-7.2.2", "auto_shadow": True, "base": "123"}})
    calls = []
    monkeypatch.setattr(worker, 'github', lambda *args: calls.append(args))
    worker.main()
    assert len(calls) == 1
    assert calls[0][1] == {"ref": "main", "inputs": {
        "training_profile": "accuracy-7.2.2", "auto_shadow": "true"}}
