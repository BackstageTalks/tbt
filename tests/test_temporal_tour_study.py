import numpy as np
import pandas as pd
import pytest
from study_temporal_tours import partitions, choose_weight, study


def test_temporal_boundaries_keep_whole_days_and_2024_start():
    times = ['2023-12-31', '2024-01-01', '2024-10-03', '2024-12-02', '2025-01-01', '2025-04-01']
    frame = pd.DataFrame({'scheduled_at': pd.to_datetime(times, utc=True), 'match_id': range(6), 'target': [0,1,0,1,0,1], 'tour_atp': [0,1,0,1,0,1]})
    parts = partitions(frame, '2025-01-01')
    assert [p.match_id.tolist() for p in parts] == [[1], [2], [3], [4]]
    with pytest.raises(ValueError):
        partitions(pd.concat([frame, frame]), '2025-01-01')


def test_weight_selection_defaults_to_pool_on_tie_or_regression():
    y = np.array([0, 1, 0, 1])
    base = np.array([.2, .8, .2, .8])
    assert choose_weight(y, base, base) == 0
    assert choose_weight(y, base, 1-base) == 0
    assert choose_weight(y, np.full(4, .5), base) == 1


class FakeModel:
    calls = []
    def __init__(self, **kwargs):
        self.calibrator = None
    def fit(self, train, cal):
        assert train.scheduled_at.max() < cal.scheduled_at.min()
        self.calls.append((train.match_id.tolist(), cal.match_id.tolist()))
    @staticmethod
    def _calibrated(calibrator, raw):
        return raw
    def _raw(self, frame):
        return self.predict_proba(frame)
    def predict_proba(self, frame):
        return np.where(frame.match_id.to_numpy() % 2, .6, .4)


def test_study_test_labels_cannot_change_specialist_selection(tmp_path):
    dates = pd.date_range('2024-01-01', '2025-03-31', freq='D', tz='UTC').repeat(20)
    n = len(dates)
    frame = pd.DataFrame({'scheduled_at': dates, 'match_id': np.arange(n), 'target': np.arange(n)%2, 'tour_atp': (np.arange(n)//2)%2})
    a = study(frame, tmp_path/'a.json', FakeModel, starts=['2025-01-01'])
    changed = frame.copy()
    changed.loc[changed.scheduled_at >= '2025-01-01', 'target'] ^= 1
    b = study(changed, tmp_path/'b.json', FakeModel, starts=['2025-01-01'])
    assert a['folds'][0]['tour_choices'] == b['folds'][0]['tour_choices']
    assert a['overall']['all']['baseline']['accuracy'] == 1
    assert b['overall']['all']['baseline']['accuracy'] == 0
    test_ids = set(frame.loc[frame.scheduled_at >= '2025-01-01', 'match_id'])
    assert all(not test_ids.intersection(tr+cal) for tr, cal in FakeModel.calls)
    assert a['production_mutated'] is False


def test_research_workflow_cannot_publish_or_activate():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1]/'.github/workflows/protected-frozen-cdb-candidate.yml').read_text(encoding='utf-8')
    for name in ('Fit separate candidate only if immutable backup gate passed',
                 'Independently persist champion-versus-candidate offline holdout',
                 'Update signed Admin model comparison without activation',
                 'Apply extra offline gates and activate verified candidate in shadow only'):
        section = workflow.split('- name: '+name, 1)[1].split('- name:', 1)[0]
        assert 'inputs.temporal_study != true' in section
    research = workflow.split('- name: Research temporal ATP/WTA variants on verified inputs', 1)[1].split('- name:', 1)[0]
    assert 'inputs.temporal_study == true' in research
    assert 'study_temporal_tours.py' in research
