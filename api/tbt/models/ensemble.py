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
from .symmetry import MODEL_FEATURE_CONTRACT, swap_frame


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
        self.excluded_features = {"weather_serve_interaction", "weather_known"}
        self.feature_names = list(FEATURE_NAMES if feature_names is None else feature_names)
        unknown = set(self.feature_names) - set(MODEL_FEATURE_CONTRACT)
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
        # Only newly fitted 7.2.1 research candidates may select ATP weights.
        self.atp_blend_specialization = False
        self.atp_blend_weight = None
        self.atp_elo_weight = None
        self.calibrator = ProbabilityCalibrator()
        # New v7.2.1 experiment only; old models load through getattr fallback.
        self.tour_calibrators: dict[str, ProbabilityCalibrator] = {}
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
        atp_weight = getattr(self, "atp_blend_weight", None)
        if atp_weight is not None:
            if "tour_atp" not in frame or getattr(self, "atp_elo_weight", None) is None:
                raise ValueError("ATP blend requires tour and both frozen weights")
            tours = frame["tour_atp"].to_numpy(dtype=float)
            if not np.isfinite(tours).all() or not np.isin(tours, [0., 1.]).all():
                raise ValueError("ATP blend requires valid tour_atp")
            mask = tours == 1.
            if mask.any():
                elo = frame["elo_probability"].to_numpy(dtype=float)
                atp_elo = float(self.atp_elo_weight)
                p[mask] = ((1 - atp_elo) *
                           (float(atp_weight) * boost[mask] +
                            (1 - float(atp_weight)) * linear[mask]) +
                           atp_elo * elo[mask])
        return np.clip(p, .01, .99)

    @staticmethod
    def _choose_atp_blend(linear, boost, elo, labels, tours, split,
                          pooled_weight, pooled_elo_weight):
        """Tune on early ATP calibration days, approve on later ATP days only."""
        arrays = [np.asarray(v, dtype=float) for v in
                  (linear, boost, elo, labels, tours)]
        if (len({len(v) for v in arrays}) != 1
                or not 0 < split < len(arrays[0])
                or any(not np.isfinite(v).all() for v in arrays)
                or not np.isin(arrays[4], [0., 1.]).all()):
            raise ValueError("Invalid ATP blend calibration inputs")
        linear, boost, elo, labels, tours = arrays
        fit_idx = np.flatnonzero(tours[:split] == 1.)
        select_idx = np.flatnonzero(tours[split:] == 1.) + split
        evidence = {"fit_n": len(fit_idx), "selection_n": len(select_idx),
                    "minimum_log_loss_improvement": .002,
                    "brier_non_regression_required": True,
                    "accuracy_non_regression_required": True}
        if (len(fit_idx) < 250 or len(select_idx) < 120
                or len(np.unique(labels[fit_idx])) < 2
                or len(np.unique(labels[select_idx])) < 2):
            return None, {**evidence, "status": "INSUFFICIENT_DISJOINT_ATP"}

        def raw(indices, boost_weight, elo_weight):
            return np.clip(
                (1. - elo_weight) *
                (boost_weight * boost[indices] + (1. - boost_weight) * linear[indices])
                + elo_weight * elo[indices], .01, .99)

        choices = []
        for boost_weight in np.linspace(0., 1., 6):
            for elo_weight in (0., .25, .5, 1.):
                p = raw(fit_idx, float(boost_weight), float(elo_weight))
                choices.append((float(log_loss(labels[fit_idx], p, labels=[0, 1])),
                                -float(accuracy_score(labels[fit_idx], p >= .5)),
                                float(boost_weight), float(elo_weight)))
        _, _, selected_boost, selected_elo = min(choices)
        baseline = raw(select_idx, pooled_weight, pooled_elo_weight)
        candidate = raw(select_idx, selected_boost, selected_elo)
        y = labels[select_idx]
        base_loss = float(log_loss(y, baseline, labels=[0, 1]))
        candidate_loss = float(log_loss(y, candidate, labels=[0, 1]))
        base_brier = float(np.mean((baseline - y) ** 2))
        candidate_brier = float(np.mean((candidate - y) ** 2))
        base_accuracy = float(accuracy_score(y, baseline >= .5))
        candidate_accuracy = float(accuracy_score(y, candidate >= .5))
        approved = (candidate_loss + .002 < base_loss
                    and candidate_brier <= base_brier + 1e-12
                    and candidate_accuracy + 1e-12 >= base_accuracy)
        evidence.update({
            "status": "SELECTED" if approved else "GLOBAL_RETAINED",
            "pooled_boost_weight": float(pooled_weight),
            "pooled_elo_weight": float(pooled_elo_weight),
            "candidate_boost_weight": selected_boost,
            "candidate_elo_weight": selected_elo,
            "pooled_selection_log_loss": base_loss,
            "candidate_selection_log_loss": candidate_loss,
            "pooled_selection_brier": base_brier,
            "candidate_selection_brier": candidate_brier,
            "pooled_selection_accuracy": base_accuracy,
            "candidate_selection_accuracy": candidate_accuracy,
        })
        return ((selected_boost, selected_elo) if approved else None), evidence

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

    @staticmethod
    def _tour_calibration_approved(tour, kind, global_kind, loss, baseline_loss,
                                   brier, baseline_brier, margin=0.008):
        """Protect ATP and WTA proper scores on disjoint calibration days.

        Calibration selection never uses the final chronological holdout.
        Existing serialized champion inference is unaffected by this gate.
        """
        # A tour-specific Platt/isotonic fit has different parameters from
        # the pooled fit, even when both use the same method. Only identity
        # is necessarily the same transform without learned parameters.
        if (kind == global_kind == "identity"
                or not np.isfinite([loss, baseline_loss, brier, baseline_brier]).all()
                or loss + margin >= baseline_loss):
            return False
        return tour in {"atp", "wta"} and brier <= baseline_brier + 1e-12

    @classmethod
    def _choose_tour_calibrators(cls, raw, labels, tour_atp, split, global_selected):
        """Select tour calibration using ONLY held-out calibration days.

        Raw probabilities were generated by estimators trained on earlier days.
        The first calibration period fits subgroup alternatives; the later one
        judges them against the original globally selected calibrator. Neither
        the untouched test/holdout nor any future shadow outcome is consulted.
        """
        if split is None or len(raw) != len(labels) or len(raw) != len(tour_atp):
            raise ValueError("Invalid subgroup calibration inputs")
        if not (0 < split < len(raw)) or not np.isfinite(tour_atp).all():
            raise ValueError("Missing or invalid tour calibration partition")
        selected: dict[str, ProbabilityCalibrator] = {}
        evidence = {}
        for tour, tour_value in (("atp", 1.), ("wta", 0.)):
            mask = np.isclose(tour_atp, tour_value, atol=1e-8)
            fit_idx = np.flatnonzero(mask[:split])
            select_idx = np.flatnonzero(mask[split:]) + split
            if (len(fit_idx) < 250 or len(select_idx) < 120
                    or len(np.unique(labels[fit_idx])) < 2
                    or len(np.unique(labels[select_idx])) < 2):
                evidence[tour] = {"status": "INSUFFICIENT_DISJOINT_CALIBRATION",
                                  "fit_n": len(fit_idx), "selection_n": len(select_idx)}
                continue
            baseline = cls._calibrated(global_selected, raw[select_idx])
            baseline_loss = float(log_loss(labels[select_idx], baseline, labels=[0, 1]))
            baseline_brier = float(np.mean((baseline - labels[select_idx]) ** 2))
            alternatives = []
            for kind in ("identity", "platt", "isotonic"):
                if kind == "isotonic" and (len(fit_idx) < 450 or
                    len(np.unique(np.round(raw[fit_idx], 3))) < 20):
                    continue
                alternative = cls._fit_calibrator(kind, raw[fit_idx], labels[fit_idx])
                p = cls._calibrated(alternative, raw[select_idx])
                score = float(log_loss(labels[select_idx], p, labels=[0, 1]))
                brier = float(np.mean((p - labels[select_idx]) ** 2))
                alternatives.append((score, brier, kind))
            # Never pick an ATP or WTA calibrator which improves log loss but
            # worsens Brier on the disjoint selection slice.
            margin = 0.008
            approved = [entry for entry in alternatives
                        if cls._tour_calibration_approved(
                            tour, entry[2], global_selected.kind,
                            entry[0], baseline_loss, entry[1], baseline_brier, margin)]
            best_loss, best_brier, best_kind = min(
                approved if approved else alternatives, key=lambda row: row[0])
            accepted = bool(approved)
            if accepted:
                all_idx = np.flatnonzero(mask)
                selected[tour] = cls._fit_calibrator(best_kind, raw[all_idx], labels[all_idx])
            evidence[tour] = {
                "status": "SELECTED" if accepted else "GLOBAL_RETAINED",
                "fit_n": len(fit_idx), "selection_n": len(select_idx),
                "global_selection_log_loss": baseline_loss,
                "best_selection_log_loss": best_loss,
                "global_selection_brier_score": baseline_brier,
                "best_selection_brier_score": best_brier,
                "selected_kind": best_kind if accepted else global_selected.kind,
                "wta_brier_non_regression_required": tour == "wta",
                "brier_non_regression_required": True,
                "minimum_improvement": margin,
                "global_kind": global_selected.kind,
                "alternatives": [
                    {"kind": kind, "selection_log_loss": loss,
                     "selection_brier_score": brier,
                     "approved": cls._tour_calibration_approved(
                         tour, kind, global_selected.kind, loss, baseline_loss,
                         brier, baseline_brier, margin)}
                    for loss, brier, kind in alternatives
                ],
            }
        return selected, evidence

    def _predict_with_tour_calibration(self, frame, raw):
        p = self._calibrated(self.calibrator, raw)
        tour_calibrators = getattr(self, "tour_calibrators", {}) or {}
        if not tour_calibrators:
            return p
        tour_values = frame["tour_atp"].to_numpy(dtype=float)
        if not np.isfinite(tour_values).all():
            raise ValueError("Tour-specific calibration requires valid tour_atp")
        for tour, value in (("atp", 1.), ("wta", 0.)):
            calibrator = tour_calibrators.get(tour)
            if calibrator is None:
                continue
            mask = np.isclose(tour_values, value, atol=1e-8)
            if mask.any():
                p[mask] = self._calibrated(calibrator, raw[mask])
        return np.clip(p, .01, .99)

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
        # Preserve BOTH orientations of every original training match.
        # Materialize only their numeric feature matrices: duplicating a full
        # ~million-row pandas training frame (including metadata columns) used
        # substantial extra RAM on the protected GitHub runner.
        left = self._matrix(train)
        x = np.empty((2 * len(train), left.shape[1]), dtype=left.dtype)
        x[:len(train)] = left
        del left
        x[len(train):] = self._matrix(swap_frame(train))
        target = train.target.to_numpy(dtype=int)
        y = np.concatenate((target, 1 - target), axis=0)
        self.linear.fit(x, y)
        self.boost.fit(x, y)
        self.blend_weight, self.elo_weight = .5, 0.
        self.atp_blend_weight, self.atp_elo_weight = None, None
        self.calibrator = ProbabilityCalibrator()
        self.tour_calibrators = {}
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
            # Nonpromoting ATP/WTA research report on disjoint calibration days.
            # Never changes blended probabilities, the accepted ATP weights,
            # calibration choice, final holdout, or frozen serving parameters.
            if (self.objective == "log_loss"
                    and getattr(self, "atp_blend_specialization", False)
                    and "tour_atp" in cal.columns):
                from .tour_blend_experiment import compare_tour_blends
                self.metadata["tour_blend_experiment"] = compare_tour_blends(
                    linear, boost, elo, y_cal, cal["tour_atp"].to_numpy(dtype=float),
                    split, (self.blend_weight, self.elo_weight),
                )
            if (self.objective == "log_loss"
                    and getattr(self, "atp_blend_specialization", False)
                    and "tour_atp" in cal.columns):
                selected, evidence = self._choose_atp_blend(
                    linear, boost, elo, y_cal, cal["tour_atp"].to_numpy(dtype=float),
                    split, self.blend_weight, self.elo_weight)
                if selected is not None:
                    self.atp_blend_weight, self.atp_elo_weight = selected
                self.metadata["atp_blend_validation"] = evidence
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
            # Use the same disjoint selection slice to choose a subgroup
            # calibrator; never optimize against the final test outcomes.
            global_selected = self._fit_calibrator(kind, raw[:split], y_cal[:split])
            if (self.objective == "log_loss" and "tour_atp" in cal.columns
                    and len(cal) >= 500):
                self.tour_calibrators, tour_evidence = self._choose_tour_calibrators(
                    raw, y_cal, cal["tour_atp"].to_numpy(dtype=float),
                    split, global_selected,
                )
                self.metadata["tour_calibration_validation"] = tour_evidence
            self.calibrator = self._fit_calibrator(kind, raw, y_cal)
            self.metadata.update({"calibrator_fit_matches": split,
                                  "calibrator_selection_matches": len(cal) - split,
                                  "calibration_candidates": dict((k, v) for v, k in candidates)})
        else:
            self.metadata["calibration_fallback"] = "insufficient disjoint calendar days"
        self.metadata.update({"blend_weight_boost": self.blend_weight,
                              "elo_weight": self.elo_weight,
                              "atp_blend_weight_boost": self.atp_blend_weight,
                              "atp_elo_weight": self.atp_elo_weight,
                              "calibration_method": self.calibrator.kind,
                              "tour_calibration_methods": {
                                  k: v.kind for k, v in self.tour_calibrators.items()
                              }})
        self.fitted = True
        return self

    def fit_frozen(
        self,
        train_frame,
        calibration_frame,
        *,
        blend_weight: float,
        elo_weight: float,
        calibrator_kind: str,
        tour_calibrator_kinds: dict[str, str] | None = None,
        atp_blend_weight: float | None = None,
        atp_elo_weight: float | None = None,
    ):
        """Refit a serving artifact without re-selecting model choices.

        This is used only after an untouched holdout has approved the candidate.
        The base estimators learn from the expanded serving-train period while
        the already-selected blend/Elo weights and calibrator *type* stay frozen.
        The calibrator parameters may be refit on the later disjoint serving
        calibration period because those outcomes are already consumed and will
        never be used again for a promotion decision.
        """
        self.fitted = False
        if len(train_frame) < 300:
            raise ValueError("At least 300 training matches are required")
        if calibrator_kind not in {"identity", "platt", "isotonic"}:
            raise ValueError("Unsupported frozen calibrator kind")
        if not 0.0 <= float(blend_weight) <= 1.0:
            raise ValueError("blend_weight must be 0..1")
        if not 0.0 <= float(elo_weight) <= 1.0:
            raise ValueError("elo_weight must be 0..1")
        if (atp_blend_weight is None) != (atp_elo_weight is None):
            raise ValueError("Frozen ATP blend requires both weights")
        if atp_blend_weight is not None and (
                not 0 <= float(atp_blend_weight) <= 1
                or not 0 <= float(atp_elo_weight) <= 1
                or not np.isfinite([atp_blend_weight, atp_elo_weight]).all()):
            raise ValueError("Invalid frozen ATP blend weights")
        if atp_blend_weight is not None and (
                "tour_atp" not in train_frame or "tour_atp" not in calibration_frame):
            raise ValueError("Frozen ATP blend requires tour_atp")

        train = train_frame.sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)
        cal = calibration_frame.sort_values(["scheduled_at", "match_id"]).reset_index(drop=True)
        if cal.empty:
            raise ValueError("Serving calibration partition is empty")
        for part in (train, cal):
            if part["match_id"].duplicated().any():
                raise ValueError("Duplicate match IDs in model partition")
            if not part["target"].isin([0, 1]).all():
                raise ValueError("Targets must be binary")
            if pd.to_datetime(part["scheduled_at"], utc=True).isna().any():
                raise ValueError("Missing match timestamps")

        train_end = pd.to_datetime(train.scheduled_at, utc=True).max().normalize()
        cal_start = pd.to_datetime(cal.scheduled_at, utc=True).min().normalize()
        if train_end >= cal_start or set(train.match_id) & set(cal.match_id):
            raise ValueError("Training and calibration must be disjoint whole UTC days")

        # Preserve BOTH orientations of every original training match.
        # Materialize only their numeric feature matrices: duplicating a full
        # ~million-row pandas training frame (including metadata columns) used
        # substantial extra RAM on the protected GitHub runner.
        left = self._matrix(train)
        x = np.empty((2 * len(train), left.shape[1]), dtype=left.dtype)
        x[:len(train)] = left
        del left
        x[len(train):] = self._matrix(swap_frame(train))
        target = train.target.to_numpy(dtype=int)
        y = np.concatenate((target, 1 - target), axis=0)
        self.linear.fit(x, y)
        self.boost.fit(x, y)

        self.blend_weight = float(blend_weight)
        self.elo_weight = float(elo_weight)
        self.atp_blend_weight = (None if atp_blend_weight is None else float(atp_blend_weight))
        self.atp_elo_weight = (None if atp_elo_weight is None else float(atp_elo_weight))
        self.calibrator = ProbabilityCalibrator()
        self.tour_calibrators = {}
        if calibrator_kind != "identity":
            raw = self._raw(cal)
            self.calibrator = self._fit_calibrator(
                calibrator_kind,
                raw,
                cal.target.to_numpy(dtype=int),
            )

        kinds = tour_calibrator_kinds or {}
        if set(kinds) - {"atp", "wta"} or any(
            kind not in {"platt", "isotonic", "identity"} for kind in kinds.values()
        ):
            raise ValueError("Invalid frozen tour calibration kind")
        if kinds:
            if "tour_atp" not in cal.columns:
                raise ValueError("Missing tour_atp for frozen subgroup refit")
            raw = self._raw(cal)
            vals = cal["tour_atp"].to_numpy(dtype=float)
            targets = cal.target.to_numpy(dtype=int)
            for tour, value in (("atp", 1.), ("wta", 0.)):
                kind = kinds.get(tour)
                if kind is None:
                    continue
                mask = np.isclose(vals, value, atol=1e-8)
                if mask.sum() < 250 or len(np.unique(targets[mask])) < 2:
                    raise ValueError("Insufficient frozen tour calibration rows")
                self.tour_calibrators[tour] = self._fit_calibrator(
                    kind, raw[mask], targets[mask],
                )

        self.metadata = {
            "objective": self.objective,
            "feature_names": self.feature_names,
            "excluded_features": sorted(self.excluded_features),
            "symmetric_inference": True,
            "training_matches": len(train),
            "blend_weight_boost": self.blend_weight,
            "elo_weight": self.elo_weight,
            "atp_blend_weight_boost": self.atp_blend_weight,
            "atp_elo_weight": self.atp_elo_weight,
            "calibration_method": self.calibrator.kind,
            "tour_calibration_methods": {
                k: v.kind for k, v in self.tour_calibrators.items()
            },
            "frozen_serving_refit": True,
            "serving_calibration_matches": len(cal),
        }
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
        return self._predict_with_tour_calibration(frame, self._raw(frame))
