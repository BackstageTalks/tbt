from datetime import datetime, timedelta, timezone
from collections import deque
import pandas as pd
import pytest
from tbt.models.feature_builder import FeatureBuilder, PlayerState, RecentPerformance, EVIDENCE_FEATURE_NAMES
from tbt.models.symmetry import swap_frame
from tbt.services.training import PRODUCTION_FEATURE_NAMES, _candidate_feature_names

NOW = datetime(2025, 6, 1, 12, tzinfo=timezone.utc)

def observation(days, surface='hard', serve=.6, returns=None):
    return RecentPerformance(NOW-timedelta(days=days), 1., .5, surface, serve_quality=serve, return_quality=returns)

def test_evidence_rejects_future_same_day_old_and_missing_stats():
    state = PlayerState(recent=deque([observation(-1), observation(.1), observation(366), observation(120), observation(1, serve=None)]))
    depth = FeatureBuilder._evidence_depth(state, NOW, 'indoor_hard')
    assert depth['serve_evidence_depth'] == pytest.approx(.5/20)
    assert depth['return_evidence_depth'] == 0
    assert depth['surface_serve_evidence_depth'] == depth['serve_evidence_depth']
    assert depth['recent_history_depth'] > depth['serve_evidence_depth']
    assert FeatureBuilder._evidence_depth(state, NOW, 'clay')['surface_serve_evidence_depth'] == 0
    assert FeatureBuilder._evidence_depth(state, NOW, 'unknown')['recent_surface_history_depth'] == 0

def test_evidence_uses_weaker_player_and_is_swap_invariant(match_factory):
    builder = FeatureBuilder()
    builder.update(match_factory('one', 'A', 'C', 'A', day=1))
    match = match_factory('two', 'A', 'B', None, day=2)
    snapshot = builder.snapshot(match)
    assert all(snapshot[n] == 0 for n in EVIDENCE_FEATURE_NAMES)
    builder.update(match_factory('three', 'B', 'D', 'B', day=1))
    snapshot = builder.snapshot(match)
    assert snapshot['recent_history_depth'] > 0
    frame = pd.DataFrame([snapshot])
    pd.testing.assert_frame_equal(frame[EVIDENCE_FEATURE_NAMES], swap_frame(frame)[EVIDENCE_FEATURE_NAMES])

def test_evidence_is_candidate_only_and_finite():
    assert not set(EVIDENCE_FEATURE_NAMES) & set(PRODUCTION_FEATURE_NAMES)
    assert set(EVIDENCE_FEATURE_NAMES) <= set(_candidate_feature_names(evidence_depth=True))
    state = PlayerState(recent=deque([observation(1, serve=float('nan'), returns=float('inf'))]))
    depth = FeatureBuilder._evidence_depth(state, NOW, 'hard')
    assert depth['serve_evidence_depth'] == depth['return_evidence_depth'] == 0
