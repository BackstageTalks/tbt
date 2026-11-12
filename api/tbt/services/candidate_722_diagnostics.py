"""Read-only confidence/evidence diagnostics for a frozen 7.2.2 candidate.

All bands use the *champion's* confidence as a fixed selection anchor when
a champion exists, so both probabilities are scored on the same fixtures.
This is an offline diagnostic, NOT issuance, calibrated TOP ROI, or promotion.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..models.metrics import wilson_interval

BANDS = (
    ("below_65", 0.0, 0.65),
    ("65_to_70", 0.65, 0.70),
    ("70_to_75", 0.70, 0.75),
    ("75_to_80", 0.75, 0.80),
    ("80_plus", 0.80, 1.01),
)
EVIDENCE_FLAGS = (
    "stats_known_both", "surface_stats_known_both", "rank_known_both",
)


def _score(probabilities, labels, selection):
    p = probabilities[selection]
    y = labels[selection]
    n = len(p)
    if not n:
        return {"n": 0, "wins": 0, "accuracy": None,
                "mean_confidence": None, "calibration_gap": None,
                "accuracy_ci95_wilson": None, "brier_score": None,
                "log_loss": None}
    chosen = p >= 0.5
    wins = int((chosen == y).sum())
    confidence = np.maximum(p, 1 - p)
    # Point-in-time winner correctness is the target for confidence; report
    # both the estimated mean and observed fraction, never one lucky hit.
    return {
        "n": n, "wins": wins, "accuracy": wins / n,
        "mean_confidence": float(confidence.mean()),
        "calibration_gap": float(wins / n - confidence.mean()),
        "accuracy_ci95_wilson": wilson_interval(wins, n),
        "brier_score": float(np.mean((p - y) ** 2)),
        "log_loss": float(np.mean(-y * np.log(p) - (1 - y) * np.log1p(-p))),
    }


def _same_fixture(candidate, champion, labels, anchor, group):
    bands = {}
    for name, lo, hi in BANDS:
        selected = group & (anchor >= lo) & (anchor < hi)
        candidate_score = _score(candidate, labels, selected)
        champion_score = (_score(champion, labels, selected)
                          if champion is not None else None)
        bands[name] = {
            "n": candidate_score["n"],
            "candidate": candidate_score,
            "champion": champion_score,
            "accuracy_delta": (candidate_score["accuracy"] - champion_score["accuracy"]
                               if champion_score and candidate_score["n"] else None),
            "brier_delta": (candidate_score["brier_score"] - champion_score["brier_score"]
                            if champion_score and candidate_score["n"] else None),
            "log_loss_delta": (candidate_score["log_loss"] - champion_score["log_loss"]
                               if champion_score and candidate_score["n"] else None),
        }
    return {"n": int(group.sum()), "bands": bands}


def candidate_722_confidence_evidence_report(test, candidate_p, champion_p=None):
    """Evaluate untouched 7.2.2 holdout; never use it to select model weights.

    Evidence flags establish model-time *availability* only, not the capture
    timestamp or denominator of the underlying serve/return/rank source.
    Missing or ambiguous evidence is not silently interpreted as good.
    """
    if test.empty:
        return {"status": "NO_ELIGIBLE_HOLDOUT", "promotion_ready": False}
    needed = {"match_id", "scheduled_at", "target", "tour", "surface",
              *EVIDENCE_FLAGS}
    missing = needed - set(test.columns)
    if missing:
        raise ValueError("7.2.2 diagnostics missing verified holdout columns: "
                         + ", ".join(sorted(missing)))
    identities = test["match_id"].astype(str).str.strip()
    if identities.eq("").any() or identities.duplicated().any():
        raise ValueError("7.2.2 diagnostics require distinct match identities")
    dates = pd.to_datetime(test["scheduled_at"], utc=True, errors="coerce")
    if dates.isna().any():
        raise ValueError("7.2.2 diagnostics require valid match timestamps")
    labels = pd.to_numeric(test["target"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(labels).all() or not np.isin(labels, (0., 1.)).all():
        raise ValueError("7.2.2 diagnostics require strictly binary outcomes")
    labels = labels.astype(int)
    candidate = np.asarray(candidate_p, dtype=float)
    champion = None if champion_p is None else np.asarray(champion_p, dtype=float)
    for name, p in (("candidate", candidate), ("champion", champion)):
        if p is None:
            continue
        if (p.ndim != 1 or len(p) != len(test)
                or not np.isfinite(p).all() or np.any(p <= 0) or np.any(p >= 1)):
            raise ValueError("7.2.2 diagnostics require aligned, finite "
                             + name + " probabilities strictly between 0 and 1")
    flags = {}
    for field in EVIDENCE_FLAGS:
        values = pd.to_numeric(test[field], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all() or not np.isin(values, (0., 1.)).all():
            raise ValueError("Invalid point-in-time feature availability: " + field)
        flags[field] = values.astype(bool)
    tours = test["tour"].astype(str).str.upper().to_numpy()
    if not np.isin(tours, ("ATP", "WTA")).all():
        raise ValueError("7.2.2 diagnostics require exact ATP/WTA tours")
    raw_surfaces = test["surface"].astype(str).str.lower().to_numpy()
    surfaces = np.where(np.isin(raw_surfaces, ("hard", "clay", "grass", "carpet")),
                        raw_surfaces, "unknown")
    anchor = np.maximum(champion, 1 - champion) if champion is not None else np.maximum(candidate, 1 - candidate)
    groups = {
        "overall": {"all": np.ones(len(test), dtype=bool)},
        "tour": {tour: tours == tour for tour in ("ATP", "WTA")},
        "surface": {surface: surfaces == surface
                    for surface in ("hard", "clay", "grass", "carpet", "unknown")},
        "input_evidence": {
            "paired_serve_return": flags["stats_known_both"],
            "missing_paired_serve_return": ~flags["stats_known_both"],
            "paired_surface_serve_return": flags["surface_stats_known_both"],
            "missing_paired_surface_serve_return": ~flags["surface_stats_known_both"],
            "both_ranks_known": flags["rank_known_both"],
            "one_or_both_ranks_missing": ~flags["rank_known_both"],
        },
        "tour_paired_serve_return": {
            tour: (tours == tour) & flags["stats_known_both"]
            for tour in ("ATP", "WTA")
        },
    }
    return {
        "status": ("PAIRED_UNSEEN_722_DIAGNOSTIC" if champion is not None
                   else "CANDIDATE_ONLY_NOT_COMPARABLE"),
        "promotion_ready": False,
        "holdout_only": True,
        "selection_anchor": ("champion_confidence" if champion is not None
                             else "candidate_confidence_no_comparison"),
        "confidence_band_policy": "65/70/75/80 fixed pre-evaluation; no odds/ROI gate",
        "rows": len(test),
        "dates_utc": {"first": dates.min().isoformat(), "last": dates.max().isoformat()},
        "evidence_coverage": {
            field: {"known_both": int(values.sum()),
                    "coverage": float(values.mean())}
            for field, values in flags.items()
        },
        "source_freshness": {
            "status": "UNVERIFIED",
            "reason": "Feature availability flags alone do not prove source capture times or point denominators",
        },
        "groups": {
            dimension: {
                name: _same_fixture(candidate, champion, labels, anchor, selected)
                for name, selected in members.items()
            }
            for dimension, members in groups.items()
        },
        "notes": [
            "Candidate and champion are scored on identical baseline-selected fixtures.",
            "This offline holdout is not an issued TOP or real-odds ROI evaluation.",
            "Never select calibration, thresholds or features using these holdout outcomes.",
            "Promotion requires independent forward shadow and exact artifact/rollback evidence.",
        ],
    }
