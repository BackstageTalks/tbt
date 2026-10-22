import pandas as pd
import pytest
from tbt.services.training import _candidate_learning_window, _split_by_date


def test_recent_window_preserves_features_and_disjoint_days():
    dates = pd.date_range('2023-12-01', periods=200, tz='UTC')
    frame = pd.DataFrame({'scheduled_at': dates, 'match_id': range(200),
                          'elo_probability': [.73]*200})
    recent = _candidate_learning_window(frame, 'top-7.2.1')
    assert recent.scheduled_at.min() == pd.Timestamp('2024-01-01', tz='UTC')
    assert (recent.elo_probability == .73).all()
    assert len(frame) == 200
    train, cal, test = _split_by_date(recent, .70, .15)
    assert train.scheduled_at.max() < cal.scheduled_at.min()
    assert cal.scheduled_at.max() < test.scheduled_at.min()
    assert len(train)+len(cal)+len(test) == len(recent)
    assert _candidate_learning_window(frame, 'standard') is frame


def test_no_old_data_fallback_and_utc_boundary():
    frame = pd.DataFrame({'scheduled_at': ['2024-01-01T00:30:00+01:00']})
    with pytest.raises(ValueError, match='2024'):
        _candidate_learning_window(frame, 'top-7.2.1')
