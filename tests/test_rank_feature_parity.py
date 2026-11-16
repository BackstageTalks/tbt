from datetime import date, datetime, timedelta, timezone
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tbt.data.atp_rank_history import ATP_RANK_HISTORY_FEATURE_NAMES, ATPRankHistory
from tbt.data.wta_rank_history import WTARankHistory
from tbt.services.engine import predict
from tbt.services.training import _pit_rank_frame_inplace, _pit_rank_snapshot, _candidate_feature_names
from tbt.models.symmetry import swap_frame


ROOT = Path(__file__).resolve().parents[1]


class _ATPRankSource:
    def features_for_match(self, match):
        values = {name: 0.0 for name in ATP_RANK_HISTORY_FEATURE_NAMES}
        values["atp_hist_rank_advantage"] = 0.75
        values["atp_hist_known_both"] = 1.0
        return values


def test_rank_enabled_artifact_requires_verified_serving_input(match_factory):
    now = datetime(2025, 1, 2, tzinfo=timezone.utc)
    fixture = match_factory("future", "A", "B", None, day=3)
    model = SimpleNamespace(
        version="rank-test",
        feature_names=["atp_hist_rank_advantage"],
        predict_proba=lambda frame: np.full(len(frame), 0.7),
    )

    with pytest.raises(ValueError, match="ATP rank-history model requires"):
        predict(model, [], [fixture], now)


def test_rank_enabled_artifact_receives_same_feature_at_serving(match_factory):
    now = datetime(2025, 1, 2, tzinfo=timezone.utc)
    fixture = match_factory("future", "A", "B", None, day=3)

    def probabilities(frame):
        assert list(frame.columns) == ["atp_hist_rank_advantage"]
        assert frame.iloc[0]["atp_hist_rank_advantage"] == pytest.approx(0.75)
        return np.full(len(frame), 0.7)

    model = SimpleNamespace(
        version="rank-test",
        feature_names=["atp_hist_rank_advantage"],
        predict_proba=probabilities,
    )
    rows = predict(
        model,
        [],
        [fixture],
        now,
        atp_rank_history=_ATPRankSource(),
    )
    assert len(rows) == 1
    assert rows[0]["model_version"] == "rank-test"



def test_protected_rank_feature_parity_overrides_unverified_match_ranks():
    # Existing canonical/current ranks may be zero, stale or today's snapshot.
    # The candidate must use precisely the earlier weekly archive in all
    # train/calibration/holdout and live serving frames.
    frame = pd.DataFrame({
        "tour_atp": [1., 1., 0., 0.],
        "atp_hist_known_both": [1., 0., 0., 0.],
        "atp_hist_rank_advantage": [0.75, 2.1, 0., 0.],
        "wta_hist_known_both": [0., 0., 1., 0.],
        "wta_hist_rank_advantage": [0., 0., -0.4, 2.5],
        "rank_known_both": [0., 1., 1., 1.],
        "rank_advantage": [-9., -7., 9., 7.],
    })
    report = _pit_rank_frame_inplace(frame)
    assert report["status"] == "PIT_WEEKLY_ALIGNED"
    assert report["known_both_rows"] == 2
    np.testing.assert_allclose(frame.rank_known_both, [1., 0., 1., 0.])
    np.testing.assert_allclose(frame.rank_advantage, [0.75, 0., -0.4, 0.])
    features = {"atp_hist_known_both": 1., "atp_hist_rank_advantage": 0.75,
                "rank_known_both": 0., "rank_advantage": -9.}
    _pit_rank_snapshot(features, "atp")
    assert features["rank_known_both"] == frame.rank_known_both.iloc[0]
    assert features["rank_advantage"] == frame.rank_advantage.iloc[0]


def test_protected_rank_feature_parity_rejects_absent_or_corrupt_weekly_inputs():
    with pytest.raises(ValueError, match="Missing frozen weekly"):
        _pit_rank_snapshot({"rank_advantage": 99.}, "atp")
    with pytest.raises(ValueError, match="Invalid pre-match"):
        _pit_rank_snapshot({"atp_hist_known_both": 0.5,
                            "atp_hist_rank_advantage": 1.}, "atp")
    missing = pd.DataFrame({"tour_atp": [1.]})
    with pytest.raises(ValueError, match="Missing point-in-time"):
        _pit_rank_frame_inplace(missing)


def test_protected_rank_feature_parity_is_applied_at_live_inference(match_factory):
    fixture = match_factory("future-weekly", "A", "B", None, tour="atp", day=3)
    fixture.player1_rank, fixture.player2_rank = 2500, 40
    now = fixture.scheduled_at.replace(day=2)

    def predict_probabilities(frame):
        assert list(frame.columns) == ["rank_advantage", "rank_known_both"]
        assert float(frame.iloc[0]["rank_known_both"]) == 1.
        assert float(frame.iloc[0]["rank_advantage"]) == pytest.approx(.75)
        return np.array([.64])

    model = SimpleNamespace(
        version="weekly-pit-candidate",
        metadata={"rank_feature_source": "point_in_time_weekly"},
        feature_names=["rank_advantage", "rank_known_both"],
        predict_proba=predict_probabilities,
    )
    rows = predict(model, [], [fixture], now, atp_rank_history=_ATPRankSource())
    assert len(rows) == 1
    assert rows[0]["confidence"] == pytest.approx(.64)
    # A metadata-controlled candidate may not silently use refreshed provider
    # rank fields when its signed weekly source is absent.
    with pytest.raises(ValueError, match="Missing frozen weekly"):
        predict(model, [], [fixture], now)


def test_absolute_pit_rank_strength_distinguishes_2500_from_50_with_same_ratio():
    dt = date(2026, 9, 28)
    snapshots = [
        {"date": dt, "rank": r, "points": 200, "name": n}
        for n, r in (("Top Alpha", 50), ("Top Beta", 100),
                     ("Tail Alpha", 2500), ("Tail Beta", 5000))
    ]
    history = ATPRankHistory(snapshots)
    def matchup(a, b):
        return SimpleNamespace(tour="atp",
                               scheduled_at=datetime(2026, 9, 29, 12, tzinfo=timezone.utc),
                               player1_name=a, player2_name=b)
    elite = history.features_for_match(matchup("Top Alpha", "Top Beta"))
    tail = history.features_for_match(matchup("Tail Alpha", "Tail Beta"))
    assert elite["atp_hist_known_both"] == tail["atp_hist_known_both"] == 1.
    assert elite["atp_hist_rank_advantage"] == pytest.approx(tail["atp_hist_rank_advantage"], abs=.01)
    assert elite["atp_hist_worst_rank_log"] == pytest.approx(math.log1p(100))
    assert tail["atp_hist_worst_rank_log"] == pytest.approx(math.log1p(5000))
    assert tail["atp_hist_best_rank_log"] == pytest.approx(math.log1p(2500))
    # These invariant strength covariates cannot change when sides swap.
    frame = pd.DataFrame([tail])
    mirrored = swap_frame(frame)
    assert mirrored["atp_hist_best_rank_log"].iloc[0] == tail["atp_hist_best_rank_log"]
    assert mirrored["atp_hist_worst_rank_log"].iloc[0] == tail["atp_hist_worst_rank_log"]
    assert mirrored["atp_hist_rank_advantage"].iloc[0] == pytest.approx(
        -tail["atp_hist_rank_advantage"])


def test_new_absolute_rank_features_remain_opt_in_for_protected_candidates():
    legacy = _candidate_feature_names(atp_rank_history=object(), wta_rank_history=object())
    protected = _candidate_feature_names(atp_rank_history=object(), wta_rank_history=object(),
                                         pit_rank_aligned=True)
    for tour in ("atp", "wta"):
        for suffix in ("best_rank_log", "worst_rank_log"):
            name = f"{tour}_hist_{suffix}"
            assert name not in legacy
            assert name in protected
    assert "rank_advantage" in legacy
    assert "rank_advantage" not in protected  # no duplicate relative rank
    assert "rank_known_both" in protected      # evidence-gate parity retained

def test_pipeline_wires_rank_history_into_train_backtest_and_serving():
    source = (ROOT / "scripts" / "pipeline.py").read_text(encoding="utf-8")
    assert "load_rank_feature_inputs" in source
    assert "atp_rank_history=atp_rank_history" in source
    assert "wta_rank_history=wta_rank_history" in source
    assert "production_requires_rank_history" in source
    assert "rank_enabled_shadow_disabled" in source


def test_backtest_uses_candidate_rank_history_contract():
    source = (ROOT / "api" / "tbt" / "services" / "backtest_service.py").read_text(
        encoding="utf-8"
    )
    assert "_augment_atp_rank_history_features" in source
    assert "_augment_wta_rank_history_features" in source
    assert "atp_rank_history=atp_rank_history" in source
    assert "wta_rank_history=wta_rank_history" in source



def test_compact_atp_rank_state_round_trips_current_and_momentum(match_factory):
    as_of = date(2026, 10, 7)
    rows = []
    for days, rank_a, rank_b in ((105, 30, 70), (84, 25, 65), (28, 20, 60), (7, 15, 55)):
        source_date = as_of - timedelta(days=days)
        rows.extend([
            {"date": source_date, "rank": rank_a, "points": 2000 + days, "name": "Alpha"},
            {"date": source_date, "rank": rank_b, "points": 1000 + days, "name": "Beta"},
        ])
    source = ATPRankHistory(rows)
    state = source.export_state(
        [{"tour": "atp", "player_id": "A", "name": "Alpha"},
         {"tour": "atp", "player_id": "B", "name": "Beta"}],
        as_of_date=as_of,
    )
    restored = ATPRankHistory.from_state(state)
    match = match_factory("rank-roundtrip", "A", "B", None, tour="atp")
    match.scheduled_at = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    assert restored.features_for_match(match) == source.features_for_match(match)


def test_compact_wta_rank_state_preserves_canonical_id_crosswalk(match_factory):
    as_of = date(2026, 10, 7)
    rows = []
    for days, rank_a, rank_b in ((105, 40, 80), (84, 35, 75), (28, 30, 70), (7, 20, 60)):
        source_date = as_of - timedelta(days=days)
        rows.extend([
            {"date": source_date, "rank": rank_a, "points": 1800 + days,
             "name": "Alpha", "sackmann_player_id": "101"},
            {"date": source_date, "rank": rank_b, "points": 900 + days,
             "name": "Beta", "sackmann_player_id": "202"},
        ])
    source = WTARankHistory(
        rows,
        canonical_to_sackmann={"A": "101", "B": "202"},
    )
    state = source.export_state(
        [{"tour": "wta", "player_id": "A", "name": "Different Alpha Alias"},
         {"tour": "wta", "player_id": "B", "name": "Different Beta Alias"}],
        as_of_date=as_of,
    )
    restored = WTARankHistory.from_state(state)
    match = match_factory("wta-rank-roundtrip", "A", "B", None, tour="wta")
    match.player1_name = "Different Alpha Alias"
    match.player2_name = "Different Beta Alias"
    match.scheduled_at = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    assert restored.features_for_match(match) == source.features_for_match(match)


def test_comparator_artifact_wires_frozen_rank_state():
    source = (ROOT / "api" / "tbt" / "services" / "comparator.py").read_text(
        encoding="utf-8"
    )
    runtime = (ROOT / "api" / "tbt" / "services" / "comparator_runtime.py").read_text(
        encoding="utf-8"
    )
    assert 'artifact["atp_rank_history"]' in source
    assert 'artifact["wta_rank_history"]' in source
    assert "ATPRankHistory.from_state" in runtime
    assert "WTARankHistory.from_state" in runtime
