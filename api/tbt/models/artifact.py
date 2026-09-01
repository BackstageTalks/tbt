from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib

from ..errors import ModelNotReadyError
from .ensemble import TennisEnsemble
from .feature_builder import FEATURE_NAMES


def save_model(model: TennisEnsemble, path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "artifact_version": 1,
        "feature_names": FEATURE_NAMES,
        "model": model,
        "metadata": model.metadata,
    }
    joblib.dump(payload, target, compress=3)


def load_model(path: str) -> TennisEnsemble:
    target = Path(path)
    if not target.exists():
        raise ModelNotReadyError(
            f"Model artifact not found at {target}. Run scripts/train.py first."
        )
    payload = joblib.load(target)
    if payload.get("feature_names") != FEATURE_NAMES:
        raise ModelNotReadyError("Model feature schema does not match the running API")
    model = payload.get("model")
    if not isinstance(model, TennisEnsemble):
        raise ModelNotReadyError("Invalid model artifact")
    return model
