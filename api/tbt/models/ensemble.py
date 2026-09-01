from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..utils import clamp, logit
from .feature_builder import FEATURE_NAMES


@dataclass
class ProbabilityCalibrator:
    kind: str = "identity"
    model: Any = None

    def predict(self, probabilities: np.ndarray) -> np.ndarray:
        p = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1 - 1e-6)
        if self.kind == "platt" and self.model is not None:
            x = np.asarray([logit(v) for v in p]).reshape(-1, 1)
            return self.model.predict_proba(x)[:, 1]
        if self.kind == "isotonic" and self.model is not None:
            return np.asarray(self.model.predict(p), dtype=float)
        return p


class TennisEnsemble:
    """Regularised linear + nonlinear ensemble with out-of-time calibration."""

    def __init__(self) -> None:
        self.linear = Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        C=0.35,
                        max_iter=2000,
                        solver="lbfgs",
                        class_weight=None,
                    ),
                ),
            ]
        )
        self.boost = HistGradientBoostingClassifier(
            learning_rate=0.04,
            max_iter=260,
            max_leaf_nodes=15,
            min_samples_leaf=28,
            l2_regularization=3.0,
            early_stopping=True,
            validation_fraction=0.12,
            random_state=200,
        )
        self.blend_weight = 0.5
        self.calibrator = ProbabilityCalibrator()
        self.version = datetime.now(timezone.utc).strftime("v200-%Y%m%dT%H%M%SZ")
        self.metadata: dict[str, Any] = {}
        self.fitted = False

    @staticmethod
    def _matrix(frame: pd.DataFrame) -> np.ndarray:
        return frame[FEATURE_NAMES].astype(float).fillna(0.0).to_numpy()

    def _raw_pair(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return self.linear.predict_proba(x)[:, 1], self.boost.predict_proba(x)[:, 1]

    def _blend(self, linear_p: np.ndarray, boost_p: np.ndarray) -> np.ndarray:
        return self.blend_weight * boost_p + (1.0 - self.blend_weight) * linear_p

    def fit(
        self,
        train_frame: pd.DataFrame,
        calibration_frame: pd.DataFrame,
    ) -> "TennisEnsemble":
        if len(train_frame) < 300:
            raise ValueError("At least 300 training matches are required")
        x_train = self._matrix(train_frame)
        y_train = train_frame["target"].astype(int).to_numpy()
        self.linear.fit(x_train, y_train)
        self.boost.fit(x_train, y_train)

        if len(calibration_frame) < 120:
            self.blend_weight = 0.5
            self.calibrator = ProbabilityCalibrator("identity", None)
            self.fitted = True
            return self

        x_cal = self._matrix(calibration_frame)
        y_cal = calibration_frame["target"].astype(int).to_numpy()
        linear_p, boost_p = self._raw_pair(x_cal)

        split = max(60, int(len(y_cal) * 0.55))
        split = min(split, len(y_cal) - 40)
        y_select, y_validate = y_cal[:split], y_cal[split:]
        lin_select, lin_validate = linear_p[:split], linear_p[split:]
        boost_select, boost_validate = boost_p[:split], boost_p[split:]

        best_weight, best_loss = 0.5, float("inf")
        for weight in np.linspace(0.0, 1.0, 21):
            candidate = weight * boost_select + (1.0 - weight) * lin_select
            loss = log_loss(y_select, np.clip(candidate, 1e-6, 1 - 1e-6), labels=[0, 1])
            if loss < best_loss:
                best_loss = float(loss)
                best_weight = float(weight)
        self.blend_weight = best_weight

        select_raw = self._blend(lin_select, boost_select)
        validate_raw = self._blend(lin_validate, boost_validate)
        full_raw = self._blend(linear_p, boost_p)

        candidates: list[tuple[str, Any, float]] = [
            (
                "identity",
                None,
                float(log_loss(y_validate, np.clip(validate_raw, 1e-6, 1 - 1e-6), labels=[0, 1])),
            )
        ]

        platt = LogisticRegression(C=10.0, max_iter=1000)
        platt.fit(np.asarray([logit(v) for v in select_raw]).reshape(-1, 1), y_select)
        platt_val = platt.predict_proba(
            np.asarray([logit(v) for v in validate_raw]).reshape(-1, 1)
        )[:, 1]
        candidates.append(
            ("platt", platt, float(log_loss(y_validate, platt_val, labels=[0, 1])))
        )

        # Isotonic is only considered with enough calibration data to control variance.
        if len(y_select) >= 350 and len(np.unique(np.round(select_raw, 3))) >= 20:
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
            iso.fit(select_raw, y_select)
            iso_val = iso.predict(validate_raw)
            candidates.append(
                ("isotonic", iso, float(log_loss(y_validate, iso_val, labels=[0, 1])))
            )

        best_kind, _, _ = min(candidates, key=lambda item: item[2])
        if best_kind == "platt":
            final = LogisticRegression(C=10.0, max_iter=1000)
            final.fit(np.asarray([logit(v) for v in full_raw]).reshape(-1, 1), y_cal)
            self.calibrator = ProbabilityCalibrator("platt", final)
        elif best_kind == "isotonic":
            final = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
            final.fit(full_raw, y_cal)
            self.calibrator = ProbabilityCalibrator("isotonic", final)
        else:
            self.calibrator = ProbabilityCalibrator("identity", None)

        self.metadata["blend_weight_boost"] = self.blend_weight
        self.metadata["calibration_method"] = self.calibrator.kind
        self.fitted = True
        return self

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        if not self.fitted:
            raise RuntimeError("Model is not fitted")
        x = self._matrix(frame)
        linear_p, boost_p = self._raw_pair(x)
        raw = self._blend(linear_p, boost_p)
        return np.asarray(
            [clamp(v, 0.01, 0.99) for v in self.calibrator.predict(raw)], dtype=float
        )
