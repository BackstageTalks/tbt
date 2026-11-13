"""Regression contracts for candidate-only 7.2.2 confidence/availability audit."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tbt.services.candidate_722_diagnostics import (
    candidate_722_confidence_evidence_report,
)


def rows():
    n = 10
    return pd.DataFrame({
        "match_id": [f"native-{i}" for i in range(n)],
        "scheduled_at": pd.date_range("2026-10-01", periods=n, freq="D", tz="UTC"),
        "target": [1, 0, 1, 1, 0, 0, 1, 1, 0, 0],
        "tour": ["ATP", "WTA"] * 5,
        "surface": ["hard", "clay", "grass", "carpet", "unknown"] * 2,
        "stats_known_both": [1, 1, 0, 1, 0, 1, 0, 1, 1, 0],
        "surface_stats_known_both": [1, 0, 0, 1, 0, 1, 0, 0, 1, 0],
        "rank_known_both": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
    })


def probabilities():
    return np.array([.64, .65, .699, .70, .749, .75, .799, .80, .95, .99])


def test_fixed_baseline_confidence_bands_have_no_outcome_based_selection():
    table = rows()
    original = table.copy(deep=True)
    champion = probabilities()
    candidate = np.clip(champion + .01, .01, .99)
    result = candidate_722_confidence_evidence_report(table, candidate, champion)
    assert result["status"] == "PAIRED_UNSEEN_722_DIAGNOSTIC"
    assert result["promotion_ready"] is False
    assert result["selection_anchor"] == "champion_confidence"
    bands = result["groups"]["overall"]["all"]["bands"]
    assert {key: v["n"] for key, v in bands.items()} == {
        "below_65": 1, "65_to_70": 2, "70_to_75": 2,
        "75_to_80": 2, "80_plus": 3,
    }
    # Both models get the exact same held-out fixtures, not distinct TOP sets.
    for row in bands.values():
        assert row["candidate"]["n"] == row["champion"]["n"] == row["n"]
        if row["n"]:
            assert row["brier_delta"] == pytest.approx(
                row["candidate"]["brier_score"] - row["champion"]["brier_score"]
            )
            assert row["log_loss_delta"] == pytest.approx(
                row["candidate"]["log_loss"] - row["champion"]["log_loss"]
            )
    changed = candidate_722_confidence_evidence_report(
        table, np.full(10, .97), champion,
    )
    assert {key: v["n"] for key, v in changed["groups"]["overall"]["all"]["bands"].items()} == {
        key: v["n"] for key, v in bands.items()
    }
    pd.testing.assert_frame_equal(table, original)


def test_report_exposes_tour_surface_and_paired_feature_coverage_not_freshness():
    result = candidate_722_confidence_evidence_report(
        rows(), probabilities(), probabilities(),
    )
    assert result["groups"]["tour"]["ATP"]["n"] == 5
    assert result["groups"]["tour"]["WTA"]["n"] == 5
    assert result["groups"]["surface"]["unknown"]["n"] == 2
    assert result["groups"]["input_evidence"]["paired_serve_return"]["n"] == 6
    assert result["groups"]["input_evidence"]["missing_paired_serve_return"]["n"] == 4
    assert result["groups"]["tour_paired_serve_return"]["ATP"]["n"] == 2
    assert result["evidence_coverage"]["rank_known_both"]["known_both"] == 5
    assert result["source_freshness"]["status"] == "UNVERIFIED"
    assert "provider_requests" not in result


def test_candidate_only_never_claims_paired_success_or_promotion():
    result = candidate_722_confidence_evidence_report(rows(), probabilities())
    assert result["status"] == "CANDIDATE_ONLY_NOT_COMPARABLE"
    assert result["promotion_ready"] is False
    assert result["groups"]["overall"]["all"]["bands"]["80_plus"]["champion"] is None


@pytest.mark.parametrize("mutation,pattern", [
    (lambda d: d.drop(columns=["surface_stats_known_both"]), "missing verified"),
    (lambda d: d.assign(match_id=["same"] * len(d)), "distinct match"),
    (lambda d: d.assign(target=[.5] + d.target.tolist()[1:]), "binary outcomes"),
    (lambda d: d.assign(rank_known_both=[2] + d.rank_known_both.tolist()[1:]), "availability"),
    (lambda d: d.assign(stats_known_both=[np.nan] + d.stats_known_both.tolist()[1:]), "availability"),
    (lambda d: d.assign(tour=["ITF"] + d.tour.tolist()[1:]), "ATP/WTA"),
    (lambda d: d.assign(scheduled_at=[None] + d.scheduled_at.tolist()[1:]), "timestamps"),
])
def test_invalid_identity_labels_or_pre_match_evidence_fail_closed(mutation, pattern):
    with pytest.raises(ValueError, match=pattern):
        candidate_722_confidence_evidence_report(
            mutation(rows()), probabilities(), probabilities(),
        )


@pytest.mark.parametrize("candidate,champion", [
    (np.array([.7, .8]), probabilities()),
    (probabilities(), np.array([.3, .4])),
    (np.array([np.nan] + [.8] * 9), probabilities()),
    (np.array([0.] + [.8] * 9), probabilities()),
    (np.array([1.] + [.8] * 9), probabilities()),
])
def test_unaligned_nonfinite_or_unbounded_model_outputs_fail_closed(candidate, champion):
    with pytest.raises(ValueError, match="aligned, finite"):
        candidate_722_confidence_evidence_report(rows(), candidate, champion)


def test_training_report_only_attaches_diagnostic_to_722_candidate():
    source = Path("api/tbt/services/training.py").read_text()
    assert 'if training_profile == "accuracy-7.2.2":' in source
    assert "candidate_722_confidence_evidence_report(" in source
    assert '"candidate_722_confidence_evidence": candidate_722_report' in source
    assert "promotion_ready" not in source[source.index('candidate_722_report = None'):
                                           source.index('candidate_722_report = None') + 600]
