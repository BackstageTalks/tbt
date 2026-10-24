from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pandas as pd
import pytest
from tbt.models.momentum import opponent_momentum
from tbt.models.symmetry import swap_frame
from tbt.services.training import _candidate_feature_names, PRODUCTION_FEATURE_NAMES

NOW = datetime(2026, 10, 24, 18, tzinfo=timezone.utc)

def row(age, won, expected):
    return SimpleNamespace(played_at=NOW-timedelta(days=age), won=won, expected=expected)

def test_momentum_measures_change_not_streak():
    old = [row(d, 1, .8) for d in [40, 50, 60]]
    surprise = [row(d, 1, .2) for d in [1, 5, 10]]
    easy = [row(d, 1, .8) for d in [1, 5, 10]]
    assert opponent_momentum(old+surprise, NOW) == pytest.approx(.2)
    assert opponent_momentum(old+easy, NOW) == pytest.approx(0)

def test_same_day_future_and_sparse_history_do_not_create_momentum():
    history = [row(d, 1, .2) for d in [1, 5, 10]]
    assert opponent_momentum(history, NOW) == 0
    history += [row(d, 0, .8) for d in [40, 50, 60]]
    expected = opponent_momentum(history, NOW)
    assert opponent_momentum(history+[row(0, 0, .99), row(-1, 1, .1)], NOW) == expected

def test_swap_and_candidate_schema():
    frame = pd.DataFrame({'opponent_momentum_diff': [.2, -.1]})
    assert swap_frame(frame).opponent_momentum_diff.tolist() == [-.2, .1]
    assert 'opponent_momentum_diff' not in PRODUCTION_FEATURE_NAMES
    assert 'opponent_momentum_diff' not in _candidate_feature_names()
    assert 'opponent_momentum_diff' in _candidate_feature_names(momentum=True)
