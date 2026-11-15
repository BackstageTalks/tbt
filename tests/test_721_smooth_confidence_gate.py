"""High-confidence calibration guard for new 7.2.1 candidates only.

These deterministic tests do not train against published TOP outcomes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tbt.models.ensemble import TennisEnsemble


def _balanced_orientation_fixture(n=400):
    assert n % 4 == 0
    raw = np.r_[np.full(n // 2, .8), np.full(n // 2, .2)]
    # At p=.8 the empirical chance is .6; at p=.2 it is .4.
    y = np.r_[
        np.tile([1, 1, 1, 0, 0], n // 10),
        np.tile([1, 1, 0, 0, 0], n // 10),
    ].astype(float)
    assert len(y) == len(raw)
    return raw, y


def test_65plus_selection_is_raw_anchored_and_allows_real_shrink():
    raw, y = _balanced_orientation_fixture()
    smooth = np.where(raw > .5, .6, .4)
    accepted, report = TennisEnsemble._smooth_confidence_validation(
        raw, y, {"identity": raw, "platt": smooth},
    )
    assert report["selection_anchor"] == "uncalibrated_symmetric_probability"
    assert report["threshold_inclusive"] == .65
    assert report["rows"] == len(raw)  # Still counted after Platt falls below .65
    assert report["status"] == "EVALUATED"
    assert accepted == {"identity", "platt"}
    assert report["scores"]["platt"]["brier_score"] < report["scores"]["identity"]["brier_score"]
    assert report["scores"]["platt"]["log_loss"] < report["scores"]["identity"]["log_loss"]


def test_guard_rejects_overconfidence_even_on_raw_65pct_boundary():
    raw, y = _balanced_orientation_fixture()
    # The candidate is more extreme without any added winning signal.
    too_sharp = np.where(raw > .5, .98, .02)
    accepted, report = TennisEnsemble._smooth_confidence_validation(
        raw, y, {"identity": raw, "platt": too_sharp},
    )
    assert report["rows"] == len(raw)
    assert accepted == {"identity"}
    assert report["scores"]["platt"]["brier_score"] > report["scores"]["identity"]["brier_score"]
    assert report["holdout_or_issued_outcomes_used"] is False

    boundary = np.r_[np.full(200, .65), np.full(200, .35)]
    accepted, report = TennisEnsemble._smooth_confidence_validation(
        boundary, y, {"identity": boundary, "platt": np.where(boundary > .5, .99, .01)},
    )
    assert report["rows"] == 400
    assert accepted == {"identity"}


def test_insufficient_high_confidence_evidence_fails_closed():
    raw, y = _balanced_orientation_fixture()
    raw[:380] = .5
    accepted, report = TennisEnsemble._smooth_confidence_validation(
        raw, y, {"identity": raw, "platt": np.full(len(raw), .5)},
    )
    assert report["rows"] == 20
    assert report["status"] == "INSUFFICIENT_HIGH_CONFIDENCE_SELECTION"
    assert accepted == {"identity"}


@pytest.mark.parametrize("bad_raw,bad_labels,bad_platt,expected", [
    (np.array([.3, np.nan]), np.array([0., 1.]), np.array([.3, .7]), "point-in-time"),
    (np.array([.3, .7]), np.array([0., .5]), np.array([.3, .7]), "point-in-time"),
    (np.array([.3, .7]), np.array([0., 1.]), np.array([.3]), "Unaligned"),
    (np.array([.3, .7]), np.array([0., 1.]), np.array([.3, np.inf]), "Unaligned"),
])
def test_invalid_probabilities_or_targets_fail_closed(bad_raw, bad_labels, bad_platt, expected):
    with pytest.raises(ValueError, match=expected):
        TennisEnsemble._smooth_confidence_validation(
            bad_raw, bad_labels, {"identity": bad_raw, "platt": bad_platt},
        )


def test_only_new_smooth_profile_invokes_confidence_gate():
    source = Path("api/tbt/models/ensemble.py").read_text()
    training = Path("api/tbt/services/training.py").read_text()
    assert 'if getattr(self, "smooth_calibration_only", False):\n                allowed,' in source
    assert 'raw[split:], y_cal[split:], candidate_predictions' in source
    assert 'evaluation_model.smooth_calibration_only = training_profile == "top-7.2.1"' in training
    # No runtime/global champion remap or odds-based calibration weights.
    assert 'if not self.metadata.get("symmetric_inference", False):' in source
