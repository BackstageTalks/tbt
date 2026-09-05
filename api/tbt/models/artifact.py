from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

from ..errors import ModelNotReadyError
from .ensemble import TennisEnsemble
from .feature_builder import FEATURE_NAMES


ARTIFACT_VERSION = 3


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(value)


def save_model(
    model: TennisEnsemble,
    path: str,
    *,
    feature_state: dict[str, Any] | None = None,
    feature_state_cutoff: datetime | str | None = None,
    feature_state_generated_at: datetime | str | None = None,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    feature_names = list(getattr(model, "feature_names", FEATURE_NAMES))
    generated = feature_state_generated_at
    if feature_state is not None and generated is None:
        generated = datetime.now(timezone.utc)

    payload: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "feature_names": feature_names,
        "model": model,
        "metadata": model.metadata,
        "feature_state": feature_state,
        "feature_state_cutoff": _iso(feature_state_cutoff),
        "feature_state_generated_at": _iso(generated),
    }

    joblib.dump(payload, target, compress=3)


def load_model(path: str) -> TennisEnsemble:
    target = Path(path)
    if not target.exists():
        raise ModelNotReadyError(
            f"Model artifact not found at {target}. Run scripts/train.py first."
        )

    payload = joblib.load(target)
    if not isinstance(payload, dict):
        raise ModelNotReadyError("Invalid model artifact payload")

    model = payload.get("model")
    if not isinstance(model, TennisEnsemble):
        raise ModelNotReadyError("Invalid model artifact")

    feature_names = payload.get("feature_names")
    if (
        not isinstance(feature_names, list)
        or not feature_names
        or not all(isinstance(feature, str) and bool(feature) for feature in feature_names)
    ):
        raise ModelNotReadyError("Model artifact contains no valid feature schema")

    # V2 compatibility: feature names always lived in the artifact even when the
    # TennisEnsemble instance itself did not persist them.
    model.feature_names = list(feature_names)

    # V3 carries a compact replay checkpoint.  Attach it to the model instead of
    # changing TennisEnsemble's public API, which keeps older inference code and
    # model lifecycle tooling compatible.
    model.feature_state = payload.get("feature_state")
    model.feature_state_cutoff = payload.get("feature_state_cutoff")
    model.feature_state_generated_at = payload.get("feature_state_generated_at")
    model.artifact_version = int(payload.get("artifact_version") or 1)

    return model
