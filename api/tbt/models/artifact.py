from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib

from ..errors import ModelNotReadyError
from .ensemble import TennisEnsemble
from .feature_builder import FEATURE_NAMES


ARTIFACT_VERSION = 2


def save_model(
    model: TennisEnsemble,
    path: str,
) -> None:
    target = Path(
        path
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    feature_names = list(
        getattr(
            model,
            "feature_names",
            FEATURE_NAMES,
        )
    )

    payload: dict[
        str,
        Any,
    ] = {
        "artifact_version": (
            ARTIFACT_VERSION
        ),
        "feature_names": (
            feature_names
        ),
        "model": (
            model
        ),
        "metadata": (
            model.metadata
        ),
    }

    joblib.dump(
        payload,
        target,
        compress=3,
    )


def load_model(
    path: str,
) -> TennisEnsemble:
    target = Path(
        path
    )

    if not target.exists():
        raise ModelNotReadyError(
            f"Model artifact not found at {target}. "
            "Run scripts/train.py first."
        )

    payload = joblib.load(
        target
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise ModelNotReadyError(
            "Invalid model artifact payload"
        )

    model = payload.get(
        "model"
    )

    if not isinstance(
        model,
        TennisEnsemble,
    ):
        raise ModelNotReadyError(
            "Invalid model artifact"
        )

    feature_names = (
        payload.get(
            "feature_names"
        )
    )

    if (
        not isinstance(
            feature_names,
            list,
        )
        or not feature_names
        or not all(
            isinstance(
                feature,
                str,
            )
            and bool(
                feature
            )
            for feature
            in feature_names
        )
    ):
        raise ModelNotReadyError(
            "Model artifact contains "
            "no valid feature schema"
        )

    # Backward compatibility:
    #
    # Older TennisEnsemble artifacts were fitted before the model
    # stored feature_names on the instance. The artifact itself has
    # always carried the feature list, so attach that exact historical
    # schema to the loaded model.
    model.feature_names = list(
        feature_names
    )

    return model
