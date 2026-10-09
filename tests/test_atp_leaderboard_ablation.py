"""Fail-closed contracts for the read-only ATP leaderboard candidate evaluation."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from audit_atp_leaderboard_ablation import (
    CAL_END, TRAIN_END, FEATURES, coverage, make_arm, paired_report, split_atp,
)
from tbt.data.atp_leaderboards import ATP_LEADERBOARD_FEATURE_NAMES


def _frame():
    rows = []
    for i, (when, tour, known) in enumerate([
        ("2023-01-01T00:00:00Z", "atp", 1),
        ("2026-06-30T23:59:59Z", "atp", 0),
        ("2026-07-01T00:00:00Z", "atp", 1),
        ("2026-08-31T23:59:59Z", "atp", 0),
        ("2026-09-01T00:00:00Z", "atp", 1),
        ("2026-09-02T00:00:00Z", "wta", 0),
    ]):
        row = {
            "match_id": f"id{i}", "scheduled_at": when, "tour": tour,
            "target": i % 2, "atp_leaderboard_known_both": float(known),
            "atp_surface_leaderboard_known_both": float(known),
        }
        for feature in FEATURES:
            row.setdefault(feature, 0.)
        rows.append(row)
    return pd.DataFrame(rows)


def test_month_end_and_same_day_split_without_mixing():
    train, calibration, test = split_atp(_frame())
    assert train.match_id.tolist() == ["id0", "id1"]
    assert calibration.match_id.tolist() == ["id2", "id3"]
    assert test.match_id.tolist() == ["id4"]
    assert TRAIN_END == "2026-07-01"
    assert CAL_END == "2026-09-01"
    assert coverage(test)["both_players_all_surface"] == 1


def test_duplicate_identity_invalid_target_and_missing_features_fail_closed():
    frame = _frame()
    with pytest.raises(ValueError, match="duplicate"):
        split_atp(pd.concat([frame, frame.iloc[:1]], ignore_index=True))
    broken = frame.copy()
    broken.loc[0, "target"] = 3
    with pytest.raises(ValueError, match="Invalid target"):
        split_atp(broken)
    with pytest.raises(ValueError, match="Missing causal"):
        split_atp(frame.drop(columns=["atp_serve_rating_diff"]))


def test_both_arms_have_identical_feature_contract_only_blind_control():
    control = make_arm(enabled=False)
    candidate = make_arm(enabled=True)
    assert control.feature_names == candidate.feature_names == FEATURES
    assert set(ATP_LEADERBOARD_FEATURE_NAMES).issubset(control.excluded_features)
    assert set(ATP_LEADERBOARD_FEATURE_NAMES).isdisjoint(candidate.excluded_features)


def test_pairing_sign_and_identical_case():
    target = np.array([0, 1, 0, 1, 0, 1])
    baseline = np.full(6, 0.5)
    same = paired_report(target, baseline, baseline)
    assert same["paired_log_loss_delta"] == 0.
    assert same["delta_candidate_minus_baseline"]["accuracy"] == 0.
    candidate = np.array([0.1, 0.9, 0.1, 0.9, 0.1, 0.9])
    improved = paired_report(target, baseline, candidate)
    assert improved["paired_log_loss_delta"] < 0.
    assert improved["delta_candidate_minus_baseline"]["brier_score"] < 0.
    assert improved["delta_candidate_minus_baseline"]["accuracy"] > 0.
    with pytest.raises(ValueError, match="aligned"):
        paired_report(target, baseline, candidate[:-1])
