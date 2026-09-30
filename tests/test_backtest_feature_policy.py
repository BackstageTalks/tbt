from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import tbt.services.backtest_service as backtest_service
from tbt.services.training import PRODUCTION_FEATURE_NAMES


def test_walk_forward_backtest_uses_governed_production_model(monkeypatch):
    rows = []
    start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    for i in range(600):
        rows.append({
            "match_id": f"h-{i}",
            "scheduled_at": start + timedelta(hours=12 * i),
            "target": i % 2,
            "elo_probability": 0.5,
        })
    test_start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    for i in range(150):
        rows.append({
            "match_id": f"t-{i}",
            "scheduled_at": test_start + timedelta(hours=12 * i),
            "target": i % 2,
            "elo_probability": 0.5,
        })
    frame = pd.DataFrame(rows)

    class FakeBuilder:
        def build_training_frame(self, matches):
            return frame.copy()

    calls = []

    class FakeModel:
        def __init__(self):
            self.metadata = {"feature_names": list(PRODUCTION_FEATURE_NAMES)}

        def fit(self, train, calibration):
            calls.append((len(train), len(calibration)))
            return self

        def predict_proba(self, test):
            return np.full(len(test), 0.5, dtype=float)

    monkeypatch.setattr(backtest_service, "audit_history", lambda matches: (list(matches), {}))
    monkeypatch.setattr(
        backtest_service,
        "_enforce_rank_provenance",
        lambda matches: (list(matches), {}),
    )
    monkeypatch.setattr(backtest_service, "FeatureBuilder", FakeBuilder)
    monkeypatch.setattr(backtest_service, "_new_production_ensemble", FakeModel)

    report = backtest_service.walk_forward_backtest(
        [object()],
        min_training_rows=500,
        first_test_year=2023,
    )

    assert calls
    assert report["tested_matches"] == 150
    assert report["folds"][0]["model_metadata"]["feature_names"] == PRODUCTION_FEATURE_NAMES
