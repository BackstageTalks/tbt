from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone
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
        self.evidence_calibrators: dict[str, ProbabilityCalibrator] = {}
        self.version = datetime.now(timezone.utc).strftime("v201-%Y%m%dT%H%M%S%fZ")
        self.metadata: dict[str, Any] = {}
        # Disabled for legacy and 7.2.1; candidate-only research opt-in.
        self.time_decay_variant_search = False
        self.training_half_life_days: int | None = None
        self.training_weight_selection: dict[str, Any] | None = None
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
    def _choose_tour_calibrators(cls, raw, labels, tour_atp, split, global_selected, *, allow_isotonic=True,
                                protect_high_confidence=False):
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
            fitted_alternatives = {}
            confidence_checks = {}
            for kind in (("identity", "platt", "isotonic") if allow_isotonic else ("identity", "platt")):
                if kind == "isotonic" and (len(fit_idx) < 450 or
                    len(np.unique(np.round(raw[fit_idx], 3))) < 20):
                    continue
                alternative = cls._fit_calibrator(kind, raw[fit_idx], labels[fit_idx])
                if (protect_high_confidence and kind == "platt"
                        and alternative.model.coef_[0, 0] <= 0):
                    continue
                p = cls._calibrated(alternative, raw[select_idx])
                fitted_alternatives[kind] = alternative
                if protect_high_confidence:
                    allowed, audit = cls._smooth_confidence_validation(
                        raw[select_idx], labels[select_idx],
                        {"identity": baseline, "override": p})
                    confidence_checks[kind] = {**audit, "approved": "override" in allowed}
                score = float(log_loss(labels[select_idx], p, labels=[0, 1]))
                brier = float(np.mean((p - labels[select_idx]) ** 2))
                alternatives.append((score, brier, kind))
            # Never pick an ATP or WTA calibrator which improves log loss but
            # worsens Brier on the disjoint selection slice.
            margin = 0.008
            approved = [entry for entry in alternatives
                        if (not protect_high_confidence or confidence_checks[entry[2]]["approved"])
                        and cls._tour_calibration_approved(
                            tour, entry[2], global_selected.kind,
                            entry[0], baseline_loss, entry[1], baseline_brier, margin)]
            best_loss, best_brier, best_kind = min(
                approved if approved else alternatives, key=lambda row: row[0])
            accepted = bool(approved)
            if accepted:
                all_idx = np.flatnonzero(mask)
                selected[tour] = (fitted_alternatives[best_kind] if protect_high_confidence
                                  else cls._fit_calibrator(best_kind, raw[all_idx], labels[all_idx]))
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
                "high_confidence_validation": confidence_checks,
                "refit_on_selection": not protect_high_confidence,
                "alternatives": [
                    {"kind": kind, "selection_log_loss": loss,
                     "selection_brier_score": brier,
                     "approved": (not protect_high_confidence or confidence_checks[kind]["approved"])
                     and cls._tour_calibration_approved(
                         tour, kind, global_selected.kind, loss, baseline_loss,
                         brier, baseline_brier, margin)}
                    for loss, brier, kind in alternatives
                ],
            }
        return selected, evidence


    @classmethod
    def _selection_tour_baseline(cls, raw, labels, tour_atp, split, global_selected,
                                 tour_calibrators):
        """Score later selection days without fitting their outcomes.

        The approved tour map in self.tour_calibrators is refitted on ALL
        calibration rows for final serving. Reusing it to choose a second
        evidence map would leak selection-day labels into the benchmark.
        Refit only the approved METHOD on earlier days for this benchmark.
        """
        raw = np.asarray(raw, dtype=float)
        labels = np.asarray(labels, dtype=float)
        tour_atp = np.asarray(tour_atp, dtype=float)
        if (raw.ndim != 1 or labels.shape != raw.shape or tour_atp.shape != raw.shape
                or not 0 < split < len(raw) or not np.isfinite(raw).all()
                or not np.isfinite(labels).all() or not np.isin(labels, [0, 1]).all()
                or not np.isfinite(tour_atp).all()
                or not np.isin(tour_atp, [0, 1]).all()):
            raise ValueError("Invalid point-in-time tour baseline inputs")
        baseline = cls._calibrated(global_selected, raw)
        for tour, value in (("atp", 1.), ("wta", 0.)):
            approved = tour_calibrators.get(tour)
            if approved is None:
                continue
            if approved.kind not in {"identity", "platt", "isotonic"}:
                raise ValueError("Invalid selected tour calibration family")
            mask = tour_atp == value
            fit_idx = np.flatnonzero(mask[:split])
            if len(fit_idx) < 250 or len(np.unique(labels[fit_idx])) < 2:
                raise ValueError("Insufficient earlier point-in-time tour evidence")
            earlier = cls._fit_calibrator(approved.kind, raw[fit_idx],
                                          labels[fit_idx].astype(int))
            baseline[mask] = cls._calibrated(earlier, raw[mask])
        return baseline

    @staticmethod
    def _evidence_cohorts(frame):
        """Side-symmetric pre-match feature availability, not odds or rank cutoffs."""
        required = {"stats_known_both", "rank_known_both"}
        if not required.issubset(frame.columns):
            raise ValueError("Evidence calibration requires point-in-time availability flags")
        stats = frame["stats_known_both"].to_numpy(dtype=float)
        ranks = frame["rank_known_both"].to_numpy(dtype=float)
        if any(not np.isfinite(values).all() or not np.isin(values, [0., 1.]).all()
               for values in (stats, ranks)):
            raise ValueError("Nonbinary or missing point-in-time availability evidence")
        return {
            f"stats_{s}_rank_{r}": (stats == float(s)) & (ranks == float(r))
            for s in (0, 1) for r in (0, 1)
        }

    @classmethod
    def _choose_evidence_calibrators(cls, raw, labels, frame, split, global_selected, baseline_probabilities=None,
                                    *, protect_high_confidence=False):
        """Approve monotone quality calibration on disjoint later days only.

        Match outcomes are used ONLY in the earlier calibration period, never
        the final holdout. No arbitrary bookmaker-price or ranking ban.
        """
        raw = np.asarray(raw, dtype=float)
        labels = np.asarray(labels, dtype=float)
        if (raw.ndim != 1 or labels.ndim != 1 or len(raw) != len(labels)
                or len(raw) != len(frame) or not 0 < split < len(raw)
                or not np.isfinite(raw).all() or not np.isfinite(labels).all()
                or not np.isin(labels, [0, 1]).all()):
            raise ValueError("Invalid evidence calibration inputs")
        labels = labels.astype(int)
        baseline = (cls._calibrated(global_selected, raw)
                    if baseline_probabilities is None
                    else np.asarray(baseline_probabilities, dtype=float))
        if baseline.shape != raw.shape or not np.isfinite(baseline).all():
            raise ValueError("Invalid actual selection baseline probabilities")
        selected, evidence = {}, {}
        for cohort, mask in cls._evidence_cohorts(frame).items():
            fit_idx = np.flatnonzero(mask[:split])
            select_idx = np.flatnonzero(mask[split:]) + split
            audit = {"fit_n": int(len(fit_idx)),
                     "selection_n": int(len(select_idx)),
                     "baseline_kind": global_selected.kind,
                     "calibrator_family": "monotone_platt",
                     "evaluation": "disjoint_calibration_days"}
            if (len(fit_idx) < 250 or len(select_idx) < 120
                    or len(np.unique(labels[fit_idx])) < 2
                    or len(np.unique(labels[select_idx])) < 2):
                evidence[cohort] = {**audit, "status": "INSUFFICIENT_DISJOINT_CALIBRATION"}
                continue
            original = baseline[select_idx]
            base_loss = float(log_loss(labels[select_idx], original, labels=[0, 1]))
            base_brier = float(np.mean((original - labels[select_idx]) ** 2))
            fitted = cls._fit_calibrator("platt", raw[fit_idx], labels[fit_idx])
            slope = float(fitted.model.coef_[0, 0])
            audit.update({"global_selection_log_loss": base_loss,
                          "global_selection_brier": base_brier})
            if not np.isfinite(slope) or slope <= 0:
                evidence[cohort] = {**audit, "status": "NONMONOTONE_REJECTED"}
                continue
            alternative = cls._calibrated(fitted, raw[select_idx])
            loss = float(log_loss(labels[select_idx], alternative, labels=[0, 1]))
            brier = float(np.mean((alternative - labels[select_idx]) ** 2))
            accepted = loss + .008 < base_loss and brier <= base_brier + 1e-12
            if protect_high_confidence:
                allowed, confidence_audit = cls._smooth_confidence_validation(
                    raw[select_idx], labels[select_idx],
                    {"identity": original, "override": alternative})
                accepted = accepted and "override" in allowed
                audit["high_confidence_validation"] = confidence_audit
                audit["refit_on_selection"] = False
            audit.update({"candidate_selection_log_loss": loss,
                          "candidate_selection_brier": brier,
                          "minimum_log_loss_improvement": .008,
                          "brier_non_regression_required": True})
            if accepted:
                all_idx = np.flatnonzero(mask)
                final = (fitted if protect_high_confidence
                         else cls._fit_calibrator("platt", raw[all_idx], labels[all_idx]))
                if float(final.model.coef_[0, 0]) > 0:
                    selected[cohort] = final
                else:
                    accepted = False
            evidence[cohort] = {**audit, "status": "SELECTED" if accepted else "GLOBAL_RETAINED"}
        return selected, evidence

    def _predict_with_tour_calibration(self, frame, raw):
        p = self._calibrated(self.calibrator, raw)
        tour_calibrators = getattr(self, "tour_calibrators", {}) or {}
        if tour_calibrators:
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
        conditional = getattr(self, "evidence_calibrators", {}) or {}
        if conditional:
            for cohort, mask in self._evidence_cohorts(frame).items():
                calibrator = conditional.get(cohort)
                if calibrator is not None and mask.any():
                    p[mask] = self._calibrated(calibrator, raw[mask])
        return np.clip(p, .01, .99)

    @staticmethod
    def _smooth_confidence_validation(raw, labels, predictions):
        """Reject newly fitted smooth maps that harm the predeclared 65%+ group.

        Only the *later* calibration-selection days are scored. The selection
        set is frozen by the uncalibrated symmetric prediction, never by a
        candidate's own probability or a bookmaker quote. This prevents a
        candidate from escaping its mistakes by moving events below 65%.
        Never consult the untouched chronological test/issuance outcomes.
        """
        raw = np.asarray(raw, dtype=float)
        labels = np.asarray(labels, dtype=float)
        if (raw.ndim != 1 or labels.shape != raw.shape or not len(raw)
                or not np.isfinite(raw).all() or np.any(raw <= 0)
                or np.any(raw >= 1) or not np.isfinite(labels).all()
                or not np.isin(labels, (0., 1.)).all()
                or not isinstance(predictions, dict) or "identity" not in predictions):
            raise ValueError("Invalid point-in-time smooth calibration evidence")
        anchored = np.maximum(raw, 1 - raw) >= 0.65
        n = int(anchored.sum())
        scores = {}
        for kind, values in predictions.items():
            p = np.asarray(values, dtype=float)
            if (p.shape != raw.shape or not np.isfinite(p).all()
                    or np.any(p <= 0) or np.any(p >= 1)):
                raise ValueError("Unaligned high-confidence calibration probabilities")
            if n:
                subset = p[anchored]
                truth = labels[anchored]
                scores[kind] = {
                    "brier_score": float(np.mean((subset - truth) ** 2)),
                    "log_loss": float(log_loss(truth, subset, labels=[0, 1])),
                    "mean_confidence": float(np.maximum(subset, 1 - subset).mean()),
                    "observed_accuracy": float(((subset >= 0.5) == truth).mean()),
                }
        # An unproven high-confidence subset cannot justify a different map.
        # Identity is the deterministic, side-symmetric fail-closed default.
        eligible = {"identity"}
        if n >= 100:
            baseline = scores["identity"]
            for kind, score in scores.items():
                if kind != "identity" and (
                    score["brier_score"] <= baseline["brier_score"] + 1e-12
                    and score["log_loss"] <= baseline["log_loss"] + 1e-12
                ):
                    eligible.add(kind)
        return eligible, {
            "status": "EVALUATED" if n >= 100 else "INSUFFICIENT_HIGH_CONFIDENCE_SELECTION",
            "selection_anchor": "uncalibrated_symmetric_probability",
            "threshold_inclusive": 0.65,
            "minimum_rows": 100,
            "rows": n,
            "selected_methods": sorted(eligible),
            "scores": scores,
            "holdout_or_issued_outcomes_used": False,
        }


    @staticmethod
    def _age_sample_weights(train: pd.DataFrame, half_life_days: int | None):
        """Fit-time decay anchored to the latest TRAINING match, not wall clock."""
        if half_life_days not in (None, 180, 365):
            raise ValueError("Unsupported candidate training half-life")
        if half_life_days is None:
            return None, {"family": "uniform", "half_life_days": None}
        dates = pd.to_datetime(train["scheduled_at"], utc=True, errors="coerce")
        if dates.isna().any() or dates.empty:
            raise ValueError("Invalid training timestamps for time weighting")
        cutoff = dates.max()
        age_days = (cutoff - dates).dt.total_seconds().to_numpy(dtype=float) / 86400.
        if not np.isfinite(age_days).all() or (age_days < 0).any():
            raise ValueError("Invalid time-decay ages")
        weights = np.exp2(-age_days / half_life_days)
        # Preserve comparable regularization strength in LogisticRegression.
        # Both orientations receive the SAME normalized per-match weight.
        weights /= weights.mean()
        if not np.isfinite(weights).all() or (weights <= 0).any():
            raise ValueError("Degenerate training weights")
        return weights, {
            "family": "exponential_half_life",
            "half_life_days": half_life_days,
            "cutoff_utc": cutoff.isoformat(),
            "normalization": "mean_one_on_original_matches",
            "min_weight": float(weights.min()),
            "max_weight": float(weights.max()),
            "effective_matches": float(weights.sum() ** 2 / np.square(weights).sum()),
        }

    def _fit_estimators(self, train: pd.DataFrame, half_life_days: int | None):
        """Reuse the original symmetric matrix contract for both estimators."""
        weights, evidence = self._age_sample_weights(train, half_life_days)
        left = self._matrix(train)
        x = np.empty((2 * len(train), left.shape[1]), dtype=left.dtype)
        x[:len(train)] = left
        del left
        x[len(train):] = self._matrix(swap_frame(train))
        target = train.target.to_numpy(dtype=int)
        y = np.concatenate((target, 1 - target), axis=0)
        if weights is None:
            # Deliberately identical to the pre-experiment legacy fit calls.
            self.linear.fit(x, y)
            self.boost.fit(x, y)
        else:
            doubled = np.concatenate((weights, weights))
            self.linear.fit(
                x, y, scale__sample_weight=doubled,
                model__sample_weight=doubled,
            )
            self.boost.fit(x, y, sample_weight=doubled)
        return evidence

    def _select_training_half_life(self, train: pd.DataFrame):
        """Compare 0/365/180 on earlier TRAIN-only UTC days, never calibration/test."""
        days = pd.to_datetime(train["scheduled_at"], utc=True).dt.normalize()
        boundaries = np.flatnonzero(days.ne(days.shift()).to_numpy())
        eligible = [int(i) for i in boundaries
                    if i >= 300 and len(train) - i >= 120]
        if not eligible:
            self.training_weight_selection = {
                "status": "INSUFFICIENT_TRAIN_ONLY_DAYS",
                "selected_half_life_days": None,
                "holdout_used": False,
            }
            return None
        split = min(eligible, key=lambda i: abs(i - .8 * len(train)))
        earlier, later = train.iloc[:split], train.iloc[split:]
        labels = later.target.to_numpy(dtype=float)
        dates = days.iloc[split:].to_numpy()
        losses, metrics = {}, {}
        for half_life in (None, 365, 180):
            trial = TennisEnsemble(feature_names=self.feature_names,
                                   objective=self.objective)
            trial.excluded_features = set(self.excluded_features)
            trial.linear = clone(self.linear)
            trial.boost = clone(self.boost)
            trial._fit_estimators(earlier, half_life)
            linear, boost = trial._symmetric_pair(later)
            # Fixed 50/50 raw blend: tuning/calibration happens later on
            # disjoint days; do not reuse later labels to choose blend weights.
            p = np.clip(.5 * (linear + boost), .01, .99)
            loss = -labels * np.log(p) - (1 - labels) * np.log1p(-p)
            key = "uniform" if half_life is None else str(half_life)
            losses[key] = loss
            metrics[key] = {
                "log_loss": float(loss.mean()),
                "brier": float(np.mean(np.square(p - labels))),
            }
        baseline = metrics["uniform"]
        selected, best_gain = None, 0.
        for half_life in (365, 180):
            key = str(half_life)
            per_day = np.array([
                float((losses["uniform"][dates == day] -
                       losses[key][dates == day]).mean())
                for day in np.unique(dates)
            ])
            stderr = (float(per_day.std(ddof=1) / np.sqrt(len(per_day)))
                      if len(per_day) > 1 else float("inf"))
            gain = baseline["log_loss"] - metrics[key]["log_loss"]
            metrics[key]["gain_vs_uniform"] = float(gain)
            metrics[key]["daily_gain_stderr"] = (
                stderr if np.isfinite(stderr) else None
            )
            # One-sided cautious screen across days, with a practical margin.
            if (gain > max(.002, 1.96 * stderr)
                    and metrics[key]["brier"] <= baseline["brier"] + 1e-12
                    and gain > best_gain):
                selected, best_gain = half_life, gain
        self.training_weight_selection = {
            "status": "TRAIN_ONLY_SELECTED" if selected else "BASELINE_RETAINED",
            "selected_half_life_days": selected,
            "candidate_metrics": metrics,
            "fit_rows": len(earlier),
            "validation_rows": len(later),
            "validation_days": int(len(np.unique(dates))),
            "fit_cutoff_utc": pd.to_datetime(earlier.scheduled_at, utc=True).max().isoformat(),
            "validation_start_utc": pd.to_datetime(later.scheduled_at, utc=True).min().isoformat(),
            "comparison": "same matches, raw symmetric 50/50 linear+boost; no calibration",
            "min_log_loss_gain": .002,
            "daily_stderr_multiplier": 1.96,
            "holdout_used": False,
            "market_odds_used": False,
        }
        return selected

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
        if getattr(self, "time_decay_variant_search", False):
            self.training_half_life_days = self._select_training_half_life(train)
        else:
            self.training_weight_selection = None
        weighting = self._fit_estimators(
            train, getattr(self, "training_half_life_days", None)
        )
        self.blend_weight, self.elo_weight = .5, 0.
        self.atp_blend_weight, self.atp_elo_weight = None, None
        self.calibrator = ProbabilityCalibrator()
        self.tour_calibrators = {}
        self.evidence_calibrators = {}
        split = calibration_split(cal) if len(cal) >= 120 else None
        self.metadata = {"objective": self.objective, "feature_names": self.feature_names,
                         "excluded_features": sorted(self.excluded_features),
                         "symmetric_inference": True, "training_matches": len(train),
                         "training_weighting": weighting,
                         "training_weight_selection": self.training_weight_selection}
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
            if getattr(self, "accuracy_blend_selection", False):
                from .accuracy_blend import select_accuracy_blend
                selected, evidence = select_accuracy_blend(
                    linear, boost, elo, y_cal, cal["tour_atp"].to_numpy(dtype=float),
                    split, (self.blend_weight, self.elo_weight))
                if selected is not None:
                    self.blend_weight, self.elo_weight = selected
                self.metadata["accuracy_blend_validation"] = evidence
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
            if (not getattr(self, "accuracy_blend_selection", False)
                    and not getattr(self, "smooth_calibration_only", False)
                    and split >= 350 and len(np.unique(np.round(raw[:split], 3))) >= 20):
                kinds.append("isotonic")
            candidates = []
            calibration_brier = {}
            candidate_predictions = {}
            for kind in kinds:
                calibrator = self._fit_calibrator(kind, raw[:split], y_cal[:split])
                if ((getattr(self, "accuracy_blend_selection", False)
                     or getattr(self, "smooth_calibration_only", False))
                     and kind == "platt" and calibrator.model.coef_[0, 0] <= 0):
                    continue
                p = self._calibrated(calibrator, raw[split:])
                candidates.append((float(log_loss(y_cal[split:], p, labels=[0, 1])), kind))
                calibration_brier[kind] = float(np.mean((p - y_cal[split:]) ** 2))
                if getattr(self, "smooth_calibration_only", False):
                    candidate_predictions[kind] = p
            if getattr(self, "smooth_calibration_only", False):
                allowed, confidence_audit = self._smooth_confidence_validation(
                    raw[split:], y_cal[split:], candidate_predictions,
                )
                self.metadata["smooth_high_confidence_validation"] = confidence_audit
                candidates = [(loss, kind) for loss, kind in candidates
                              if kind in allowed]
                # Do not cure isotonic plateaus by trading away Brier quality.
                # Identity is always eligible and preserves the original raw
                # probability when smooth Platt does not beat both scores.
                candidates = [
                    (loss, kind) for loss, kind in candidates
                    if calibration_brier[kind] <= calibration_brier["identity"] + 1e-12
                    or kind == "identity"
                ]
            _, kind = min(candidates, key=lambda item: item[0])
            if getattr(self, "smooth_calibration_only", False):
                self.metadata["smooth_calibration_brier_candidates"] = calibration_brier
            # Use the same disjoint selection slice to choose a subgroup
            # calibrator; never optimize against the final test outcomes.
            global_selected = self._fit_calibrator(kind, raw[:split], y_cal[:split])
            if (not getattr(self, "accuracy_blend_selection", False)
                    and self.objective == "log_loss" and "tour_atp" in cal.columns
                    and len(cal) >= 500):
                self.tour_calibrators, tour_evidence = self._choose_tour_calibrators(
                    raw, y_cal, cal["tour_atp"].to_numpy(dtype=float),
                    split, global_selected,
                    allow_isotonic=not getattr(self, "smooth_calibration_only", False),
                    protect_high_confidence=getattr(self, "smooth_calibration_only", False),
                )
                self.metadata["tour_calibration_validation"] = tour_evidence
            # For the protected smooth profile, retain the exact map evaluated
            # on later days. A refit would silently replace its validated slope.
            self.calibrator = (global_selected if getattr(self, "smooth_calibration_only", False)
                               else self._fit_calibrator(kind, raw, y_cal))
            self.metadata["calibration_refit_on_selection"] = not getattr(self, "smooth_calibration_only", False)
            if getattr(self, "evidence_calibration_selection", False):
                # Account for an already-selected ATP/WTA calibration when
                # deciding if a quality-cohort override helps. Comparing
                # against the pooled baseline alone can silently regress an
                # existing validated tour-specific probability.
                actual_baseline = self._calibrated(global_selected, raw)
                if self.tour_calibrators:
                    actual_baseline = self._selection_tour_baseline(
                        raw, y_cal, cal["tour_atp"].to_numpy(dtype=float),
                        split, global_selected, self.tour_calibrators,
                    )
                self.evidence_calibrators, quality_evidence = (
                    self._choose_evidence_calibrators(
                        raw, y_cal, cal, split, global_selected,
                        baseline_probabilities=actual_baseline,
                        protect_high_confidence=getattr(self, "smooth_calibration_only", False),
                    )
                )
                self.metadata["evidence_calibration_validation"] = quality_evidence
            if ((getattr(self, "accuracy_blend_selection", False)
                 or getattr(self, "smooth_calibration_only", False))
                 and kind == "platt" and self.calibrator.model.coef_[0, 0] <= 0):
                self.calibrator = ProbabilityCalibrator()
            self.metadata.update({"calibrator_fit_matches": split,
                                  "calibrator_selection_matches": len(cal) - split,
                                  "calibration_candidates": dict((k, v) for v, k in candidates)})
        else:
            self.metadata["calibration_fallback"] = "insufficient disjoint calendar days"
        self.metadata.update({"smooth_calibration_only": bool(getattr(self, "smooth_calibration_only", False)),
                              "evidence_calibration_methods": {
                                  key: cal.kind for key, cal
                                  in self.evidence_calibrators.items()},
                              "blend_weight_boost": self.blend_weight,
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
        evidence_calibrator_kinds: dict[str, str] | None = None,
        training_half_life_days: int | None = None,
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
        cohort_kinds = evidence_calibrator_kinds or {}
        allowed_cohorts = {f"stats_{s}_rank_{r}" for s in (0, 1) for r in (0, 1)}
        if (set(cohort_kinds) - allowed_cohorts
                or any(kind != "platt" for kind in cohort_kinds.values())):
            raise ValueError("Invalid frozen evidence-calibration contract")
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

        self.training_half_life_days = training_half_life_days
        weighting = self._fit_estimators(train, training_half_life_days)

        self.blend_weight = float(blend_weight)
        self.elo_weight = float(elo_weight)
        self.atp_blend_weight = (None if atp_blend_weight is None else float(atp_blend_weight))
        self.atp_elo_weight = (None if atp_elo_weight is None else float(atp_elo_weight))
        self.calibrator = ProbabilityCalibrator()
        self.tour_calibrators = {}
        self.evidence_calibrators = {}
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

        if cohort_kinds:
            # The only variables allowed to choose the frozen subgroup are
            # point-in-time model features, not refreshed market odds or later
            # ranks. Type and minimum-fit evidence must survive the refit.
            raw = self._raw(cal)
            labels = cal.target.to_numpy(dtype=int)
            masks = self._evidence_cohorts(cal)
            for cohort, kind in cohort_kinds.items():
                idx = np.flatnonzero(masks[cohort])
                if len(idx) < 250 or len(np.unique(labels[idx])) < 2:
                    raise ValueError("Insufficient frozen evidence cohort")
                fitted = self._fit_calibrator(kind, raw[idx], labels[idx])
                if float(fitted.model.coef_[0, 0]) <= 0:
                    raise ValueError("Frozen evidence calibrator lost monotonicity")
                self.evidence_calibrators[cohort] = fitted

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
            "evidence_calibration_methods": {
                k: v.kind for k, v in self.evidence_calibrators.items()
            },
            "frozen_serving_refit": True,
            "training_weighting": weighting,
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
