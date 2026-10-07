from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tbt.data.atp_rank_history import ATP_RANK_HISTORY_FEATURE_NAMES, ATPRankHistory
from tbt.data.wta_rank_history import WTARankHistory
from tbt.services.engine import predict


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
