from dataclasses import replace
from datetime import datetime, timezone
import sys
from pathlib import Path
import pandas as pd
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_existing_data_value import align_market, comparison, recovery_inventory
from tbt.models.feature_builder import FeatureBuilder


def test_service_complements_recover_quality_without_mutating_history(match_factory):
    m = replace(match_factory('a','a','b','a'),stats={'p1_service_points_won':.7,'p2_service_points_won':.6})
    counts = recovery_inventory([m])['overall']
    assert counts['locally_recoverable_rows'] == 1
    assert counts['locally_added_values'] == 2
    assert counts['new_both_ready'] == 1
    assert 'p1_return_points_won' not in m.stats


def test_market_alignment_keeps_probability_and_prices_on_oriented_player():
    assert align_market({'player1_odds':2.,'player2_odds':4.},False) == pytest.approx((2.,4.,2/3))
    assert align_market({'player1_odds':2.,'player2_odds':4.},True) == pytest.approx((4.,2.,1/3))
    stats = comparison([{'model':.7,'market':2/3,'target':1,'odds1':2.,'odds2':4.}])
    assert stats['model_all_matches_flat_yield'] == 1.
    assert stats['model_minus_market_brier'] == pytest.approx(.09 - 1/9)
    assert stats['paired_log_loss_delta_ci95_approx'] is None


def test_prior_replay_plus_recent_frame_matches_full_causal_frame(match_factory):
    history = [match_factory('a','a','b','a',1),match_factory('b','a','c','c',2),match_factory('c','b','c','b',2),match_factory('d','a','b','b',3)]
    full = FeatureBuilder().build_training_frame(history)
    builder = FeatureBuilder()
    start = datetime(2025,1,2,tzinfo=timezone.utc)
    builder.replay(history,before=start)
    recent = builder.build_training_frame([m for m in history if m.scheduled_at >= start])
    pd.testing.assert_frame_equal(full.loc[full.scheduled_at >= start].reset_index(drop=True), recent.reset_index(drop=True))
