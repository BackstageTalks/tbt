"""Smooth, data-aware 7.2.2 calibration; never a rank/odds exclusion."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tbt.models.ensemble import ProbabilityCalibrator, TennisEnsemble


def fixtures(seed=722, n=8800):
    rng = np.random.default_rng(seed)
    raw = rng.uniform(.03, .97, n)
    stats = (np.arange(n) % 2).astype(float)
    ranks = ((np.arange(n) // 2) % 2).astype(float)
    frame = pd.DataFrame({"stats_known_both": stats, "rank_known_both": ranks})
    # Conditional poor confidence is not a bad or unranked player: only an
    # observed out-of-time difference between probability and winner frequency.
    true_p = np.where(
        (stats == 1) & (ranks == 0),
        .5 + .20 * (raw - .5),
        raw,
    )
    targets = rng.binomial(1, true_p)
    return raw, targets, frame


def test_later_calibration_days_select_platt_for_miscalibrated_quality_cohort():
    raw, targets, frame = fixtures()
    chosen, evidence = TennisEnsemble._choose_evidence_calibrators(
        raw, targets, frame, 4840, ProbabilityCalibrator(),
    )
    key = "stats_1_rank_0"
    assert evidence[key]["status"] == "SELECTED"
    assert evidence[key]["fit_n"] >= 250
    assert evidence[key]["selection_n"] >= 120
    assert chosen[key].kind == "platt"
    assert chosen[key].model.coef_[0, 0] > 0
    assert (
        evidence[key]["candidate_selection_log_loss"] + .008
        < evidence[key]["global_selection_log_loss"]
    )
    assert (
        evidence[key]["candidate_selection_brier"]
        <= evidence[key]["global_selection_brier"]
    )
    # A selected group preserves ordering/side but changes overconfidence.
    corrected = TennisEnsemble._calibrated(chosen[key], np.array([.83, .17]))
    assert corrected[0] < .83 and corrected[1] > .17
    np.testing.assert_allclose(corrected.sum(), 1., atol=1e-10)


def test_insufficient_pit_quality_evidence_keeps_global_calibration():
    raw, targets, frame = fixtures(n=400)
    # Only ~100 examples/cohort and ~55 on later selection days.
    selected, report = TennisEnsemble._choose_evidence_calibrators(
        raw, targets, frame, 220, ProbabilityCalibrator(),
    )
    assert selected == {}
    assert all(v["status"] == "INSUFFICIENT_DISJOINT_CALIBRATION"
               for v in report.values())


def test_invalid_or_future_imputed_flags_fail_closed():
    raw, labels, frame = fixtures(n=400)
    for bad in (np.nan, .5, 2.):
        corrupted = frame.copy()
        corrupted.loc[0, "stats_known_both"] = bad
        with pytest.raises(ValueError, match="Nonbinary"):
            TennisEnsemble._choose_evidence_calibrators(
                raw, labels, corrupted, 220, ProbabilityCalibrator(),
            )
    with pytest.raises(ValueError, match="point-in-time"):
        TennisEnsemble._choose_evidence_calibrators(
            raw, labels, frame.drop(columns=["rank_known_both"]),
            220, ProbabilityCalibrator(),
        )


def test_candidate_cohort_inference_is_symmetric_and_legacy_champion_unchanged():
    class Shrink:
        kind = "platt"

        def predict(self, p):
            return .5 + .2 * (np.asarray(p) - .5)

    model = TennisEnsemble()
    model.fitted = True
    model.metadata["symmetric_inference"] = True
    model._raw = lambda frame: np.array([.83, .17, .83, .17])
    frame = pd.DataFrame({
        "stats_known_both": [1., 1., 0., 0.],
        "rank_known_both": [0., 0., 1., 1.],
    })
    model.evidence_calibrators = {"stats_1_rank_0": Shrink()}
    np.testing.assert_allclose(model.predict_proba(frame), [.566, .434, .83, .17])
    del model.evidence_calibrators
    np.testing.assert_allclose(model.predict_proba(frame), [.83, .17, .83, .17])
    # Old champion has no extra dependency on stat/rank feature flags.
    np.testing.assert_allclose(
        model._predict_with_tour_calibration(pd.DataFrame(), np.array([.83, .17])),
        [.83, .17],
    )


@pytest.mark.parametrize("bad", [
    {"stats_0_rank_0": "isotonic"},
    {"stats_9_rank_9": "platt"},
    {"stats_1_rank_1": "identity"},
])
def test_serving_refit_rejects_unapproved_calibrator_schema_before_fit(bad):
    train = pd.DataFrame(index=range(300))
    with pytest.raises(ValueError, match="frozen evidence"):
        TennisEnsemble().fit_frozen(
            train, pd.DataFrame(index=range(200)), blend_weight=.5,
            elo_weight=0., calibrator_kind="identity",
            evidence_calibrator_kinds=bad,
        )


def test_candidate_selector_not_retrained_on_later_unseen_results():
    raw, labels, frame = fixtures()
    first, before = TennisEnsemble._choose_evidence_calibrators(
        raw, labels, frame, 4840, ProbabilityCalibrator(),
    )
    # The underlying selection needs only the two pre-holdout calibration
    # segments. It is deterministic and has no access to outside results.
    again, after = TennisEnsemble._choose_evidence_calibrators(
        raw.copy(), labels.copy(), frame.copy(), 4840, ProbabilityCalibrator(),
    )
    assert before == after
    assert set(first) == set(again)
    for key in first:
        np.testing.assert_allclose(
            first[key].predict(np.array([.1, .3, .8])),
            again[key].predict(np.array([.1, .3, .8])),
        )



def test_same_fixture_pit_holdout_reports_top80_accuracy_and_brier():
    from tbt.services.training import paired_evidence_holdout_diagnostics

    raw, targets, frame = fixtures(n=800)
    frame["target"] = targets
    baseline = raw
    candidate = .5 + .2 * (raw - .5)
    report = paired_evidence_holdout_diagnostics(frame, candidate, baseline)
    assert report["status"] == "PAIRED_UNSEEN_HOLDOUT"
    assert report["holdout_only"] and report["never_select_on_holdout"]
    assert sum(v["n"] for v in report["cohorts"].values()) == len(frame)
    for cohort, value in report["cohorts"].items():
        assert value["candidate"]["n"] == value["champion"]["n"]
        assert 0 <= value["candidate"]["top80_coverage"] <= 1
        assert value["same_fixture_brier_delta"] == pytest.approx(
            value["candidate"]["brier_score"] - value["champion"]["brier_score"]
        )
    unmatched = paired_evidence_holdout_diagnostics(frame, candidate)
    assert unmatched["status"] == "CANDIDATE_ONLY_NOT_PROMOTION_READY"
    assert all(v["champion"] is None for v in unmatched["cohorts"].values())
    with pytest.raises(ValueError, match="same-fixture"):
        paired_evidence_holdout_diagnostics(frame, candidate[:-1], baseline)


def test_fractional_calibration_labels_are_not_coerced_to_losses():
    raw, targets, frame = fixtures(n=400)
    contaminated = targets.astype(float)
    contaminated[0] = .5
    with pytest.raises(ValueError, match="Invalid evidence"):
        TennisEnsemble._choose_evidence_calibrators(
            raw, contaminated, frame, 220, ProbabilityCalibrator(),
        )



def test_one_shot_722_training_uses_existing_backup_lock_pipeline_without_promotion():
    from pathlib import Path

    workflow = Path(".github/workflows/protected-frozen-cdb-candidate.yml").read_text()
    assert "feat(722): one-shot PIT evidence calibration study" in workflow
    assert "&& 'accuracy-7.2.2'" in workflow
    assert "python scripts/wait_for_cdb_writer_idle.py" in workflow
    assert "python scripts/guarded_candidate_backup.py prepare" in workflow
    assert "python scripts/cdb_global_writer_lock.py acquire" in workflow
    assert "python scripts/audit_training_leakage.py" in workflow
    assert "python scripts/publish_frozen_candidate_evidence.py" in workflow
    assert "--training-profile \"$BLINQ_TRAINING_PROFILE\"" in workflow
    assert "# No --promote." in workflow
