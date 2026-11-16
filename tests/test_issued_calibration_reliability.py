"""Synthetic read-only issuance reliability regression tests."""
import math

from issued_calibration_reliability import issued_reliability, wilson95
from audit_top_reliability import picked_player_rank_2000_band


def test_five_point_bands_use_original_issued_values_and_never_fill_pending():
    rows = [
        {"probability": .60, "correct": True},
        {"probability": .64999, "correct": False},
        {"probability": .65, "correct": True},
        {"probability": .80, "correct": True},
        {"probability": .95, "correct": False},
        {"probability": .99, "correct": None},
        {"probability": None, "correct": False},
    ]
    report = issued_reliability(rows)
    assert report["status"].startswith("READ_ONLY_SELECTED_ISSUED_RELIABILITY")
    assert report["settled_with_original_confidence"] == 5
    assert report["settled_missing_original_confidence"] == 1
    assert report["unsettled_or_void"] == 1
    b = report["bands"]
    assert b["60_65"]["n"] == 2
    assert b["60_65"]["wins"] == 1
    assert abs(b["60_65"]["mean_issued_probability"] - .624995) < 1e-10
    assert b["65_70"]["wins"] == 1
    assert b["80_85"]["wins"] == 1
    assert b["95_100"]["losses"] == 1
    assert b["95_100"]["evidence"] == "SMALL_SELECTED_SAMPLE"
    assert math.isfinite(report["ece_5pp_descriptive"])
    assert len(b) == 10


def test_empty_and_invalid_do_not_claim_success():
    report = issued_reliability([
        {"probability": None, "correct": True},
        {"probability": float("nan"), "correct": False},
        {"probability": True, "correct": True},
        {"probability": .84, "correct": None},
    ])
    assert report["settled_with_original_confidence"] == 0
    assert report["settled_missing_original_confidence"] == 3
    assert report["unsettled_or_void"] == 1
    assert report["ece_5pp_descriptive"] is None
    assert all(b["observed_wilson95"] is None for b in report["bands"].values())
    assert all(b["evidence"] == "NO_SETTLED_EVIDENCE" for b in report["bands"].values())


def test_wilson_interval_high_uncertainty_for_one_80_percent_issued_pick():
    lo, hi = wilson95(1, 1)
    assert 0.15 < lo < .25
    assert hi == 1.
    assert wilson95(0, 0) is None
    lo, hi = wilson95(50, 100)
    assert .39 < lo < .41
    assert .59 < hi < .61


def test_invalid_row_shape_fails_closed():
    try:
        issued_reliability([None])
    except ValueError:
        pass
    else:
        raise AssertionError("invalid record must be rejected")


def test_mixed_model_legacy_cannot_claim_exact_issued_reliability():
    from datetime import datetime, timezone
    from audit_top_reliability import analyze
    now = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
    legacy = analyze([], now=now)
    assert "issued_probability_reliability" not in legacy
    exact = analyze([], now=now, model_version="v7.2.1-test")
    assert exact["issued_probability_reliability"]["settled_with_original_confidence"] == 0


def test_rank_2500_original_issued_cohort_is_not_merged_with_rank_1200():
    row = {"player1": {"id": "p1", "rank": 2500},
           "player2": {"id": "p2", "rank": 1200}}
    assert picked_player_rank_2000_band(row, "p1") == "pick_2000_plus"
    assert picked_player_rank_2000_band(row, "p2") == "pick_below_2000"
    assert picked_player_rank_2000_band(row, "unknown") == "rank_unknown"
    row["player1"].pop("rank")
    assert picked_player_rank_2000_band(row, "p1") == "rank_unknown"
