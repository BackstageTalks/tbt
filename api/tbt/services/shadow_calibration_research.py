"""Read-only, leakage-safe shadow probability-calibration experiment.

Never rewrites a candidate, a shadow prediction, or a publication. Platt
corrections are evaluated on a future, untouched UTC-day cohort. Only outcomes
settled before the first evaluation prediction may fit a correction.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math

import numpy as np
from sklearn.linear_model import LogisticRegression

from ..models.metrics import evaluate_probabilities


def _utc(value):
    if not value:
        raise ValueError("Missing temporal calibration provenance")
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Shadow calibration timestamps require a timezone")
    return dt.astimezone(timezone.utc)


def _metrics(rows, probabilities):
    truth = [int(row["target_player1_win"]) for row in rows]
    raw = evaluate_probabilities(truth, probabilities)
    return {
        key: (round(float(raw[key]), 8) if raw.get(key) is not None
              and math.isfinite(float(raw[key])) else None)
        for key in ("accuracy", "log_loss", "brier_score", "ece_10", "roc_auc")
    } | {"n": len(rows)}


def _logit(probabilities):
    p = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1-1e-6)
    return np.log(p / (1-p)).reshape(-1, 1)


def _fit_symmetric_platt(rows):
    p = np.asarray([float(r["challenger_player1_probability"]) for r in rows])
    y = np.asarray([int(r["target_player1_win"]) for r in rows])
    # Preserve player-orientation symmetry used by the existing TennisEnsemble.
    calibrator = LogisticRegression(C=10., max_iter=1000, fit_intercept=False)
    calibrator.fit(_logit(np.r_[p, 1-p]), np.r_[y, 1-y])
    return calibrator


def _predict_symmetric(calibrator, probabilities):
    p = np.asarray(probabilities, dtype=float)
    left = calibrator.predict_proba(_logit(p))[:, 1]
    right = calibrator.predict_proba(_logit(1-p))[:, 1]
    return np.clip(.5 * (left + 1-right), .01, .99)


def research_comparison(
    rows,
    production_version: str,
    challenger_version: str,
    *,
    minimum_fit: int = 200,
    minimum_eval: int = 100,
    minimum_tour_fit: int = 100,
):
    """Compare predeclared Platt alternatives without tuning on the test set.

    This is NOT prospective recalibration evidence for production. A model
    version receives a fresh cohort; the experiment never changes that version.
    """
    relevant = [
        r for r in rows
        if r.get("production_model_version") == production_version
        and r.get("challenger_model_version") == challenger_version
        and r.get("status") == "settled"
    ]
    result = {
        "status": "INSUFFICIENT_TEMPORAL_EVIDENCE",
        "method": "predeclared_symmetric_platt_global_and_atp_wta",
        "scope": "READ_ONLY_RESEARCH_NOT_LIVE_SHADOW_OR_PRODUCTION",
        "fit_rows": 0,
        "evaluation_rows": 0,
        "fit_utc_days": 0,
        "evaluation_utc_days": 0,
        "temporal_policy": (
            "Full UTC calendar days; fit outcomes must be recorded settled "
            "strictly before the first out-of-time evaluation prediction."
        ),
        "not_a_production_decision": True,
    }
    if not relevant:
        result["reason"] = "no_matched_settled_shadow_predictions"
        return result

    # All settlement times are required. Do not infer settlement from kickoff.
    if any(not r.get("settled_at") for r in relevant):
        result["reason"] = "missing_immutable_settlement_timestamp"
        return result
    ordered = sorted(relevant, key=lambda r: (_utc(r["scheduled_at"]), str(r["match_id"])))
    days = sorted({_utc(r["scheduled_at"]).date() for r in ordered})
    if len(days) < 6:
        result["reason"] = "fewer_than_six_settled_utc_days"
        result["settled_utc_days"] = len(days)
        return result

    first_eval_day = days[max(1, int(len(days) * .6))]
    earlier = [r for r in ordered if _utc(r["scheduled_at"]).date() < first_eval_day]
    later = [r for r in ordered if _utc(r["scheduled_at"]).date() >= first_eval_day]
    first_eval_capture = min(_utc(r["captured_at"]) for r in later)
    eligible_fit = [
        r for r in earlier
        if _utc(r["settled_at"]) < first_eval_capture
    ]
    result.update({
        "fit_rows": len(eligible_fit),
        "evaluation_rows": len(later),
        "fit_utc_days": len({_utc(r["scheduled_at"]).date() for r in eligible_fit}),
        "evaluation_utc_days": len({_utc(r["scheduled_at"]).date() for r in later}),
        "evaluation_start_utc": first_eval_capture.isoformat(),
        "cutoff_day_utc": first_eval_day.isoformat(),
        "late_settlements_excluded": len(earlier) - len(eligible_fit),
    })
    if (len(eligible_fit) < minimum_fit or len(later) < minimum_eval
            or result["fit_utc_days"] < 3 or result["evaluation_utc_days"] < 2):
        result["reason"] = "insufficient_independently_settled_fit_or_future_evaluation"
        return result

    model = _fit_symmetric_platt(eligible_fit)
    p = [float(r["challenger_player1_probability"]) for r in later]
    result["overall"] = {
        "champion": _metrics(later, [float(r["production_player1_probability"]) for r in later]),
        "candidate_original": _metrics(later, p),
        "candidate_global_platt_research": _metrics(later, _predict_symmetric(model, p)),
    }
    result["by_tour"] = {}
    for tour in ("ATP", "WTA"):
        fit_tour = [r for r in eligible_fit if str(r.get("tour") or "").upper() == tour]
        eval_tour = [r for r in later if str(r.get("tour") or "").upper() == tour]
        subset = {
            "fit_rows": len(fit_tour), "evaluation_rows": len(eval_tour),
            "status": "INSUFFICIENT_TOUR_EVIDENCE",
        }
        if len(fit_tour) >= minimum_tour_fit and len(eval_tour) >= 30:
            tour_platt = _fit_symmetric_platt(fit_tour)
            tour_p = [float(r["challenger_player1_probability"]) for r in eval_tour]
            subset.update({
                "status": "RESEARCH_EVALUATED",
                "champion": _metrics(eval_tour, [float(r["production_player1_probability"]) for r in eval_tour]),
                "candidate_original": _metrics(eval_tour, tour_p),
                "candidate_global_platt_research": _metrics(eval_tour, _predict_symmetric(model, tour_p)),
                "candidate_tour_platt_research": _metrics(eval_tour, _predict_symmetric(tour_platt, tour_p)),
            })
        result["by_tour"][tour] = subset

    result["status"] = "RESEARCH_EVALUATED"
    result["reason"] = "out_of_time_research_only_no_candidate_or_shadow_mutation"
    return result
