from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from tbt.models.ensemble import TennisEnsemble
from tbt.models.portable_export import export_portable_model
from tbt.models.portable_model import predict_probability


FEATURES = [
    "elo_diff",
    "surface_elo_diff",
    "elo_probability",
    "recent_form_diff",
    "serve_quality_diff",
    "rank_known_both",
]


def _frame(count: int, *, start: int) -> pd.DataFrame:
    rng = np.random.default_rng(1200 + start)
    rows = []
    origin = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=start)
    for idx in range(count):
        elo_diff = float(rng.normal(0, 180))
        surface = float(rng.normal(elo_diff * .6, 120))
        recent = float(rng.normal(0, .18))
        serve = float(rng.normal(0, .09))
        elo_p = 1.0 / (1.0 + np.exp(-elo_diff / 300.0))
        latent = elo_diff / 240.0 + surface / 400.0 + recent * 1.2 + serve * .8
        probability = 1.0 / (1.0 + np.exp(-latent))
        target = int(rng.random() < probability)
        rows.append({
            "match_id": f"p-{start}-{idx}",
            "scheduled_at": origin + timedelta(days=idx),
            "target": target,
            "elo_diff": elo_diff,
            "surface_elo_diff": surface,
            "elo_probability": elo_p,
            "recent_form_diff": recent,
            "serve_quality_diff": serve,
            "rank_known_both": float(idx % 4 != 0),
        })
    return pd.DataFrame(rows)


def test_portable_export_matches_sklearn_champion_predictions():
    train = _frame(320, start=0)
    calibration = _frame(140, start=400)
    model = TennisEnsemble(feature_names=FEATURES)
    model.fit(train, calibration)
    artifact = export_portable_model(model)

    probe = _frame(30, start=700)
    native = model.predict_proba(probe[FEATURES])
    portable = np.asarray([
        predict_probability(artifact, row)
        for row in probe[FEATURES].to_dict("records")
    ])

    assert artifact["model_version"] == model.version
    assert np.max(np.abs(native - portable)) < 1e-10


def test_portable_runtime_has_no_training_stack_imports():
    source = Path("api/tbt/models/portable_model.py").read_text(encoding="utf-8").lower()
    assert "import pandas" not in source
    assert "import numpy" not in source
    assert "sklearn" not in source
    assert "joblib" not in source
