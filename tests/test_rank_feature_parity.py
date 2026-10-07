from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tbt.data.atp_rank_history import ATP_RANK_HISTORY_FEATURE_NAMES
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
