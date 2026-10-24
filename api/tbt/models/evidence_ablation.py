"""Opt-in, offline paired 7.2.1/DIL ablation on an independently frozen cohort.

NOT the protected production writer. Never fetches CDB, API, market prices or
releases; never trains on the full old holdout for promotion. Requires reviewed
match/player crosswalk, individually verified available_at timestamps, original
PIT historical opponent estimates and a frozen base feature schema. Returns
only a descriptive report; no model artifact is saved or activated.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
import math

import numpy as np
import pandas as pd

from .ensemble import TennisEnsemble
from .evidence_lab import DIL_FEATURE_NAMES, HistoricalEvidence
from .evidence_training import augment_research_training_frame
from .metrics import evaluate_probabilities
from .symmetry import MODEL_FEATURE_CONTRACT


def _pin(value, field):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(field + " needs independently pinned lowercase SHA256")
    return value


def canonical_dil_evidence_digest(rows):
    """Canonical SHA256 of the complete reviewed row set, independent of row order.

    Pin this independently when freezing the exact input sidecar. It is NOT a
    claim that the original raw vendor archive or CDB backup has been verified.
    """
    serialized = []
    for item in rows:
        if not isinstance(item, HistoricalEvidence):
            raise ValueError("Expected reviewed HistoricalEvidence dataclasses")
        row = asdict(item)
        for key in ("started_at", "completed_at", "available_at", "expected_recorded_at"):
            timestamp = row[key]
            if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Timezone-aware evidence required")
            row[key] = timestamp.isoformat()
        serialized.append(row)
    serialized.sort(key=lambda x: (x["tour"], x["player_id"], x["canonical_match_id"]))
    blob = json.dumps(serialized, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)
    return sha256(blob.encode("utf-8")).hexdigest()


def _metrics(frame, baseline_p, dil_p):
    if frame.empty:
        return {"n": 0, "baseline": None, "with_dil": None, "delta": None}
    y = frame.target.to_numpy(dtype=int)
    original = evaluate_probabilities(y, np.asarray(baseline_p))
    enriched = evaluate_probabilities(y, np.asarray(dil_p))
    columns = ("accuracy", "log_loss", "brier_score", "ece_10", "roc_auc")
    delta = {}
    for key in columns:
        a, b = original.get(key), enriched.get(key)
        delta[key] = (float(b) - float(a)
                      if a is not None and b is not None and math.isfinite(a) and math.isfinite(b)
                      else None)
    return {
        "n": len(frame),
        "baseline": {key: original.get(key) for key in columns},
        "with_dil": {key: enriched.get(key) for key in columns},
        "delta": delta,
    }


def run_dil_research_ablation(
    frozen_frame, canonical_matches, verified_dil_rows, *,
    original_721_feature_names,
    canonical_source_sha256,
    dil_sidecar_sha256,
    min_paired_by_tour=30,
    estimator_max_iter=None,
):
    """Fit paired fresh research models with identical 7.2.1 hyperparameters.

    The input frozen_frame must be the same run-bound point-in-time history
    replay as the protected 7.2.1 baseline. Existing reviewed holdouts may be
    inspected for descriptive diagnostics only. Nothing in this method grants
    permission to promote or deploy the fitted model.
    """
    from tbt.services.training import _candidate_learning_window, _split_by_date

    _pin(canonical_source_sha256, "Canonical source")
    _pin(dil_sidecar_sha256, "DIL sidecar")
    verified_dil_rows = list(verified_dil_rows)
    if canonical_dil_evidence_digest(verified_dil_rows) != dil_sidecar_sha256:
        raise ValueError("Frozen DIL source row digest mismatch")
    names = tuple(original_721_feature_names)
    if (not names or len(names) != len(set(names))
            or "elo_probability" not in names
            or {"serve_quality_diff", "return_quality_diff"} - set(names)
            or set(names) & set(DIL_FEATURE_NAMES)
            or set(names) - MODEL_FEATURE_CONTRACT):
        raise ValueError("Explicit original 7.2.1 feature schema required")
    if min_paired_by_tour < 1:
        raise ValueError("Positive independently paired sample guard required")
    if estimator_max_iter is not None and (type(estimator_max_iter) is not int
                                           or estimator_max_iter < 1):
        raise ValueError("Invalid estimator test setting")
    mandatory = set(names) | {"target", "tour", "scheduled_at", "match_id", "surface"}
    if mandatory - set(frozen_frame):
        raise ValueError("Frozen 7.2.1 feature frame incomplete")
    if frozen_frame.match_id.duplicated().any():
        raise ValueError("Duplicate frozen canonical match IDs")

    augmented, coverage = augment_research_training_frame(
        frozen_frame, canonical_matches, verified_dil_rows)
    learning = _candidate_learning_window(augmented, "top-7.2.1")
    train, calibration, test = _split_by_date(learning, .70, .15)

    def paired(part):
        return part["dil_serve_known_both"].eq(1) & part["dil_return_known_both"].eq(1)

    counts = {}
    for name, part in (("train", train), ("calibration", calibration), ("descriptive_test", test)):
        counts[name] = {}
        for tour in ("atp", "wta"):
            subset = part.loc[part.tour.eq(tour)]
            usable = int(paired(subset).sum())
            counts[name][tour] = {
                "rows": len(subset), "paired_serve_return": usable,
                "paired_fraction": usable / len(subset) if len(subset) else None,
            }
            if usable < min_paired_by_tour:
                raise ValueError(f"Insufficient verified PIT DIL coverage {name}/{tour}")
    deltas = {}
    predictions = {}
    for arm, features in (
        ("baseline_721", list(names)),
        ("new_dil", list(names) + list(DIL_FEATURE_NAMES)),
    ):
        model = TennisEnsemble(feature_names=features, objective="log_loss")
        # Tests may lower max_iter; real runs use exactly the standard learner.
        if estimator_max_iter is not None:
            model.boost.set_params(max_iter=estimator_max_iter)
        model.atp_blend_specialization = True
        model.fit(train, calibration)
        predictions[arm] = model.predict_proba(test)
        deltas[arm] = {
            "feature_count": len(features),
            "calibrator": model.calibrator.kind,
            "blend_weight": model.blend_weight,
            "elo_weight": model.elo_weight,
        }
        del model

    key = pd.DataFrame({
        "match_id": learning.match_id.astype(str),
        "utc_time": pd.to_datetime(learning.scheduled_at, utc=True).map(lambda x: x.isoformat()),
    }).sort_values(["utc_time", "match_id"])
    fingerprint = sha256(key.to_json(orient="records").encode("utf-8")).hexdigest()
    baseline, candidate = predictions["baseline_721"], predictions["new_dil"]
    result = {
        "state": "OFFLINE_RESEARCH_DESCRIPTIVE_NOT_PROMOTION",
        "canonical_source_sha256": canonical_source_sha256,
        "dil_evidence_rows_canonical_sha256": dil_sidecar_sha256,
        "canonical_source_bundle_sha256_claim": canonical_source_sha256,
        "learning_cohort_identity_sha256": fingerprint,
        "feature_schema_exact_original_721": list(names),
        "candidate_extra_features": list(DIL_FEATURE_NAMES),
        "coverage": coverage, "partition_coverage": counts,
        "fit": deltas,
        "overall": _metrics(test, baseline, candidate),
        "segments": {},
        "limits": [
            "Retrospective holdout is not newly untouched promotion evidence.",
            "No model artifact is persisted; no TOP/VALUE odds or ROI measured.",
            "Only verified DIL player/match identity and PIT available-at evidence qualify.",
        ],
        "provider_requests": 0,
        "cdb_writes": 0,
        "models_promoted": 0,
        "can_promote": False,
    }
    for feature, values in (
        ("tour", ("atp", "wta")),
        ("surface", ("hard", "clay", "grass")),
    ):
        result["segments"][feature] = {}
        for v in values:
            mask = test[feature].eq(v).to_numpy()
            result["segments"][feature][v] = _metrics(
                test.loc[mask], baseline[mask], candidate[mask])
    if "competition" in test:
        result["segments"]["competition"] = {}
        for v in ("main", "challenger", "itf"):
            mask = test.competition.astype(str).str.lower().eq(v).to_numpy()
            result["segments"]["competition"][v] = _metrics(
                test.loc[mask], baseline[mask], candidate[mask])
    return result
