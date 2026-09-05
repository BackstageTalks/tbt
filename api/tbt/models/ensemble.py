from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .feature_builder import FEATURE_NAMES
from .symmetry import swap_frame


def _logits(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


@dataclass
class ProbabilityCalibrator:
    kind: str = "identity"
    model: Any = None

    def predict(self, probabilities: np.ndarray) -> np.ndarray:
        p = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1 - 1e-6)
        if self.kind == "platt" and self.model is not None:
            return self.model.predict_proba(_logits(p))[:, 1]
        if self.kind == "isotonic" and self.model is not None:
            return np.asarray(self.model.predict(p), dtype=float)
        return p


def calibration_split(frame: pd.DataFrame) -> int | None:
    """Never split one UTC day across calibration fitting and selection."""
    days = pd.to_datetime(frame["scheduled_at"], utc=True).dt.normalize()
    boundaries = np.flatnonzero(days.ne(days.shift()).to_numpy())
    valid = [int(i) for i in boundaries if i >= 60 and len(frame) - i >= 40]
    return min(valid, key=lambda i: abs(i - len(frame) * .55)) if valid else None


class TennisEnsemble:
    """Symmetric linear/boost/Elo blend selected strictly after training."""

    def __init__(self, feature_names: list[str] | None = None, objective: str = "accuracy"):
        if objective not in {"accuracy", "log_loss"}:
            raise ValueError("objective must be accuracy or log_loss")
        self.objective = objective
        # Archive weather is an observation, not a forecast known before kickoff.
        # Re-enable only after storing point-in-time forecast provenance.
        self.excluded_features = {"weather_serve_interaction", "weather_known", "environment_known"}
        self.feature_names = list(FEATURE_NAMES if feature_names is None else feature_names)
        unknown = set(self.feature_names) - set(FEATURE_NAMES)
        if unknown:
            raise ValueError(f"Features need an explicit swap contract: {sorted(unknown)}")
        self.linear = Pipeline([
            ("scale", StandardScaler()),
            ("model", LogisticRegression(C=.35, max_iter=2000, solver="lbfgs")),
        ])
        # Random early-stopping could split opposite orientations of one match.
        self.boost = HistGradientBoostingClassifier(
            learning_rate=.04, max_iter=260, max_leaf_nodes=15,
            min_samples_leaf=56, l2_regularization=3., early_stopping=False,
            random_state=200,
        )
        self.blend_weight = .5
        self.elo_weight = 0.
        self.calibrator = ProbabilityCalibrator()
        self.version = datetime.now(timezone.utc).strftime("v201-%Y%m%dT%H%M%S%fZ")
        self.metadata: dict[str, Any] = {}
        self.fitted = False

    def _matrix(self, frame):
        missing = set(self.feature_names) - set(frame.columns)
        if missing:
            raise ValueError(f"Prediction frame is missing model features: {sorted(missing)}")
        numeric = frame[self.feature_names].astype(float).fillna(0.).copy()
        for name in getattr(self, "excluded_features", set()):
            if name in numeric:
                numeric[name] = 0.
        x = numeric.to_numpy()
        if not np.isfinite(x).all():
            raise ValueError("Model features must be finite")
        return x

    def _raw_pair(self, x):
        return self.linear.predict_proba(x)[:, 1], self.boost.predict_proba(x)[:, 1]

    def _blend(self, linear_p, boost_p):
        return self.blend_weight * boost_p + (1 - self.blend_weight) * linear_p

    def _symmetric_pair(self, frame):
        linear, boost = self._raw_pair(self._matrix(frame))
        rl, rb = self._raw_pair(self._matrix(swap_frame(frame)))
        return .5 * (linear + 1 - rl), .5 * (boost + 1 - rb)

    def _raw(self, frame):
        linear, boost = self._symmetric_pair(frame)
        p = self._blend(linear, boost)
        weight = getattr(self, "elo_weight", 0.)
        if weight:
            p = (1 - weight) * p + weight * frame["elo_probability"].to_numpy(dtype=float)
        return np.clip(p, .01, .99)

    @staticmethod
    def _calibrated(calibrator, p):
        return np.clip(.5 * (calibrator.predict(p) + 1 - calibrator.predict(1 - p)), .01, .99)

    @staticmethod
    def _fit_calibrator(kind, p, y):
        probs, targets = np.r_[p, 1 - p], np.r_[y, 1 - y]
        if kind == "platt":
            model = LogisticRegression(C=10., max_iter=1000, fit_intercept=False)
            model.fit(_logits(probs), targets)
        elif kind == "isotonic":
            model = IsotonicRegression(out_of_bounds="clip", y_min=.01, y_max=.99)
            model.fit(probs, targets)
        else:
            return ProbabilityCalibrator()
        return ProbabilityCalibrator(kind, model)

    def fit(self, train_frame, calibration_frame):
        self.fitted = False
        if len(train_frame) < 300:
            raise ValueError("At least 300 training matches are required")
        train = train_frame.sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)
        cal = calibration_frame.sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)
        for part in (train, cal):
            if part["match_id"].duplicated().any():
                raise ValueError("Duplicate match IDs in model partition")
            if not part["target"].isin([0, 1]).all():
                raise ValueError("Targets must be binary")
            if pd.to_datetime(part["scheduled_at"], utc=True).isna().any():
                raise ValueError("Missing match timestamps")
        if not cal.empty:
            train_end = pd.to_datetime(train.scheduled_at, utc=True).max().normalize()
            cal_start = pd.to_datetime(cal.scheduled_at, utc=True).min().normalize()
            if train_end >= cal_start or set(train.match_id) & set(cal.match_id):
                raise ValueError("Training and calibration must be disjoint whole UTC days")
        augmented = pd.concat([train, swap_frame(train)], ignore_index=True)
        x, y = self._matrix(augmented), augmented.target.to_numpy(dtype=int)
        self.linear.fit(x, y)
        self.boost.fit(x, y)
        self.blend_weight, self.elo_weight = .5, 0.
        self.calibrator = ProbabilityCalibrator()
        split = calibration_split(cal) if len(cal) >= 120 else None
        self.metadata = {"objective": self.objective, "feature_names": self.feature_names,
                         "excluded_features": sorted(self.excluded_features),
                         "symmetric_inference": True, "training_matches": len(train)}
        if split is not None:
            linear, boost = self._symmetric_pair(cal)
            elo = cal.elo_probability.to_numpy(dtype=float)
            y_cal = cal.target.to_numpy(dtype=int)
            choices = []
            for weight in np.linspace(0., 1., 6):
                for elo_weight in (0., .25, .5, 1.):
                    p = np.clip((1 - elo_weight) * (weight * boost + (1 - weight) * linear)
                                + elo_weight * elo, .01, .99)
                    loss = float(log_loss(y_cal[:split], p[:split], labels=[0, 1]))
                    accuracy = float(accuracy_score(y_cal[:split], p[:split] >= .5))
                    score = (-accuracy, loss) if self.objective == "accuracy" else (loss, -accuracy)
                    choices.append((score, float(weight), elo_weight))
            _, self.blend_weight, self.elo_weight = min(choices, key=lambda item: item[0])
            raw = self._raw(cal)
            kinds = ["identity", "platt"]
            if split >= 350 and len(np.unique(np.round(raw[:split], 3))) >= 20:
                kinds.append("isotonic")
            candidates = []
            for kind in kinds:
                calibrator = self._fit_calibrator(kind, raw[:split], y_cal[:split])
                p = self._calibrated(calibrator, raw[split:])
                candidates.append((float(log_loss(y_cal[split:], p, labels=[0, 1])), kind))
            _, kind = min(candidates, key=lambda item: item[0])
            self.calibrator = self._fit_calibrator(kind, raw, y_cal)
            self.metadata.update({"calibrator_fit_matches": split,
                                  "calibrator_selection_matches": len(cal) - split,
                                  "calibration_candidates": dict((k, v) for v, k in candidates)})
        else:
            self.metadata["calibration_fallback"] = "insufficient disjoint calendar days"
        self.metadata.update({"blend_weight_boost": self.blend_weight,
                              "elo_weight": self.elo_weight,
                              "calibration_method": self.calibrator.kind})
        self.fitted = True
        return self

    def predict_proba(self, frame):
        if not self.fitted:
            raise RuntimeError("Model is not fitted")
        if frame.empty:
            return np.array([], dtype=float)
        # Loading an existing champion must not silently change its behaviour.
        if not self.metadata.get("symmetric_inference", False):
            linear, boost = self._raw_pair(self._matrix(frame))
            return np.clip(self.calibrator.predict(self._blend(linear, boost)), .01, .99)
        return self._calibrated(self.calibrator, self._raw(frame))
