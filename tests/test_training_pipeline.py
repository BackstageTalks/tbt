from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from tbt.schemas import MatchRecord
from tbt.services.training import _period, refit_serving_model, train_from_matches
from tbt.models.symmetry import swap_frame
from tbt.models.feature_builder import RICH_CHARTING_FEATURE_NAMES


def test_end_to_end_training_reports_real_match_counts_and_symmetric_outputs():
    rng = np.random.default_rng(24)
    matches = []
    for i in range(1200):
        a, b = rng.choice(24, 2, replace=False)
        p = 1 / (1 + np.exp(-(a - b) / 12))
        matches.append(MatchRecord(
            match_id=str(i), tour="atp", scheduled_at=datetime(2023, 1, 1, tzinfo=timezone.utc) + timedelta(days=i // 4),
            player1_id=str(a), player2_id=str(b), player1_name=str(a), player2_name=str(b),
            winner_id=str(a if rng.random() < p else b), surface="hard",
        ))
    result = train_from_matches(matches, min_matches=1000)
    report = result.report
    assert sum(report["data"][k] for k in ("train", "calibration", "holdout")) == 1200
    assert report["holdout"]["selective_accuracy"][0]["n"] == report["data"]["holdout"]
    frame = result.feature_frame.tail(20)
    assert np.allclose(result.model.predict_proba(frame) + result.model.predict_proba(swap_frame(frame)), 1)
    assert not (set(RICH_CHARTING_FEATURE_NAMES) & set(result.model.feature_names))
    assert set(RICH_CHARTING_FEATURE_NAMES).issubset(result.feature_frame.columns)

    serving = refit_serving_model(result)
    assert serving.metadata["serving_refit"] is True
    assert serving.metadata["selection_model_version"] == result.model.version
    assert serving.metadata["history_end"] == (
        result.feature_frame["scheduled_at"].max().isoformat()
    )
    assert serving.metadata["production_train_matches"] > report["data"]["train"]
    assert serving.metadata["production_calibration_matches"] > 0
    assert serving.blend_weight == result.model.blend_weight
    assert serving.elo_weight == result.model.elo_weight
    assert serving.calibrator.kind == result.model.calibrator.kind


def test_empty_evaluation_period_is_explicitly_none():
    frame = pd.DataFrame({"scheduled_at": pd.Series([], dtype="datetime64[ns, UTC]")})
    assert _period(frame) == {"start": None, "end": None}


def test_training_report_contains_production_subgroups_contract():
    source = (ROOT / "api" / "tbt" / "services" / "training.py").read_text(encoding="utf-8")
    assert '"production_subgroups": production_subgroups' in source
    assert "subgroup_report(test, production_probabilities)" in source


def test_promotion_gate_requires_atp_and_wta_non_regression():
    source = (ROOT / "scripts" / "pipeline.py").read_text(encoding="utf-8")
    assert 'for tour in ("atp", "wta")' in source
    assert 'f"{tour}_promotion_sample_missing_or_below_50"' in source
    assert 'f"{tour}_accuracy_worse_than_production"' in source
    assert 'f"{tour}_{key}_worse_than_production"' in source
    assert 'f"{tour}_no_probabilistic_improvement_vs_production"' in source
