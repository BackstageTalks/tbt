"""Private model calibration: never reuse old pairs or spent holdouts."""
import unittest
from datetime import datetime, timezone, timedelta

from tbt.services.model_calibration_status import (
    normalize_model_calibration_snapshot, with_freshness,
)


def fixture():
    return {
        "schema": 1,
        "source_generated_at": "2026-10-09T06:00:00Z",
        "production_version": "champion-v1",
        "candidate_version": "challenger-v2",
        "shadow": {
            "production_model_version": "champion-v1",
            "challenger_model_version": "challenger-v2",
            "cohort": {
                "captured": 140, "settled": 105, "pending": 35,
                "settled_utc_days": 4, "minimum_for_review": 200,
            },
            "production": {
                "accuracy": 0.68, "log_loss": 0.59,
                "brier_score": 0.21, "ece_10": 0.07,
            },
            "challenger": {
                "accuracy": 0.71, "log_loss": 0.55,
                "brier_score": 0.19, "ece_10": 0.06,
            },
            "gate": {
                "minimum_matches_met": False,
                "minimum_days_met": True,
                "accuracy_not_worse": True,
                "log_loss_better": True,
                "brier_better": True,
                "ece_not_worse": True,
                "ready_for_promotion_review": False,
                "automatic_promotion": False,
            },
        },
        "readiness": {
            "production_version": "champion-v1",
            "generated_at_utc": "2026-10-09T05:00:00Z",
            "eligible_unseen_rows": 29,
            "eligible_unseen_days": 1,
            "minimum_gate_rows": 200,
            "recommended_target_rows": 1000,
        },
        "last_decision": {
            "status": "rejected",
            "candidate_version": "old-challenger",
            "production_version": "champion-v1",
            "decided_at": "2026-10-08T12:00:00Z",
            "reason_codes": ["brier_worse"],
        },
    }


class TestModelCalibrationStatus(unittest.TestCase):
    def test_progress_separates_shadow_and_unseen_samples(self):
        report = normalize_model_calibration_snapshot(fixture())
        self.assertEqual(report["shadow"]["settled"], 105)
        self.assertEqual(report["shadow"]["remaining_to_review"], 95)
        self.assertEqual(report["shadow"]["remaining_to_target"], 895)
        self.assertEqual(report["unseen"]["eligible_rows"], 29)
        self.assertEqual(report["unseen"]["remaining_to_review"], 171)
        self.assertEqual(report["unseen"]["remaining_to_target"], 971)
        self.assertFalse(report["last_decision"]["same_pair"])
        self.assertFalse(report["automatic_promotion"])
        self.assertEqual(report["research_branch"], "research/model-calibration")

    def test_new_champion_does_not_inherit_stale_readiness(self):
        source = fixture()
        source["production_version"] = "champion-v3"
        source["candidate_version"] = "candidate-v4"
        source["shadow"]["production_model_version"] = "champion-v3"
        source["shadow"]["challenger_model_version"] = "candidate-v4"
        source["shadow"]["cohort"] = {
            "captured": 0, "settled": 0, "pending": 0,
            "settled_utc_days": 0, "minimum_for_review": 200,
        }
        result = normalize_model_calibration_snapshot(source)
        self.assertFalse(result["unseen"]["available"])
        self.assertIsNone(result["unseen"]["eligible_rows"])
        self.assertIsNone(result["unseen"]["remaining_to_target"])
        self.assertFalse(result["last_decision"]["same_pair"])
        self.assertEqual(result["shadow"]["remaining_to_target"], 1000)

    def test_wrong_pair_fails_closed(self):
        source = fixture()
        source["shadow"]["challenger_model_version"] = "unexpected"
        with self.assertRaises(ValueError):
            normalize_model_calibration_snapshot(source)

    def test_unrealistic_counts_fail_closed(self):
        source = fixture()
        source["shadow"]["cohort"]["settled"] = 141
        with self.assertRaises(ValueError):
            normalize_model_calibration_snapshot(source)

    def test_reused_decision_is_historical_even_with_good_metrics(self):
        source = fixture()
        source["last_decision"]["candidate_version"] = "challenger-v2"
        result = normalize_model_calibration_snapshot(source)
        self.assertTrue(result["last_decision"]["same_pair"])
        self.assertEqual(result["last_decision"]["status"], "rejected")
        self.assertFalse(result["shadow"]["gate"]["ready_for_promotion_review"])

    def test_frozen_candidate_is_separate_from_old_shadow(self):
        source = fixture()
        source["offline_candidate"] = {
            "schema": 1,
            "status": "EVALUATED_NOT_DEPLOYED",
            "evaluation_type": "untouched_offline_holdout",
            "promotion_requested": False,
            "model_promoted": False,
            "backup_readback_verified": True,
            "champion_restore_verified": True,
            "candidate_remote_readback_verified": True,
            "champion_version": "champion-v1",
            "candidate_version": "new-frozen-v3",
            "candidate_release_tag": "blinq-candidate-frozen-123-1",
            "candidate_sha256": "f" * 64,
            "backup_tag": "blinq-full-training-backup-123-1",
            "run_id": "123",
            "generated_at_utc": "2026-10-13T23:30:00Z",
            "comparison": {
                "sample_size": 500,
                "champion": {"n": 500, "accuracy": .70, "log_loss": .58,
                             "brier_score": .20, "ece_10": .04},
                "candidate": {"n": 500, "accuracy": .72, "log_loss": .56,
                              "brier_score": .19, "ece_10": .04},
            },
        }
        result = normalize_model_calibration_snapshot(source)
        self.assertEqual(result["shadow"]["settled"], 105)
        self.assertEqual(result["candidate_version"], "challenger-v2")
        self.assertEqual(result["offline_candidate"]["candidate_version"], "new-frozen-v3")
        self.assertEqual(result["offline_candidate"]["n"], 500)
        self.assertFalse(result["offline_candidate"]["model_promoted"])

    def test_frozen_candidate_fails_closed_on_unequal_samples(self):
        source = fixture()
        self.test_frozen_candidate_is_separate_from_old_shadow()
        source["offline_candidate"] = {
            "schema": 1, "status": "EVALUATED_NOT_DEPLOYED",
            "evaluation_type": "untouched_offline_holdout",
            "promotion_requested": False, "model_promoted": False,
            "backup_readback_verified": True, "champion_restore_verified": True,
            "candidate_remote_readback_verified": True,
            "champion_version": "champion-v1", "candidate_version": "new-v2",
            "candidate_release_tag": "blinq-candidate-frozen-123-1",
            "candidate_sha256": "f"*64, "generated_at_utc": "2026-10-13T23:30:00Z",
            "comparison": {"sample_size": 500,
                           "champion": {"n": 499, "accuracy": .70, "log_loss": .58,
                                        "brier_score": .20, "ece_10": .04},
                           "candidate": {"n": 500, "accuracy": .72, "log_loss": .56,
                                        "brier_score": .19, "ece_10": .04}},
        }
        with self.assertRaises(ValueError):
            normalize_model_calibration_snapshot(source)

    def test_snapshot_staleness_is_reported_without_changing_metrics(self):
        normalized = normalize_model_calibration_snapshot(fixture())
        normalized["updated_at"] = "2026-10-09T06:00:00+00:00"
        old = with_freshness(
            normalized, now=datetime(2026, 10, 9, 16, tzinfo=timezone.utc)
        )
        self.assertTrue(old["stale"])
        self.assertEqual(old["shadow"]["settled"], 105)
        self.assertFalse(old["promotion_permitted"])
        fresh = with_freshness(
            normalized, now=datetime(2026, 10, 9, 8, tzinfo=timezone.utc)
        )
        self.assertFalse(fresh["stale"])


def test_model_711_alias_keeps_unique_model_id_and_is_bound_to_frozen_run():
    from pathlib import Path
    ui=(Path(__file__).resolve().parents[1]/"web"/"app.js").read_text(encoding="utf-8")
    assert "String(offline.run_id)==='38486683787'" in ui
    assert "blinq-candidate-frozen-38486683787-[0-9]+" in ui
    assert "const newCandidateTitle=model711?'Model 7.1.1'" in ui
    assert "model711?'Model 7.1.1':String(offline.candidate_version||'—')" in ui
    assert "<summary>Technický pôvod a audit modelu</summary>" in ui
    assert "<details class=\"admin-calibration-audit\">" in ui
    assert "Nemenný artefakt:" in ui
    assert "Záloha tréningových vstupov:" in ui
    assert "${escapeHtml(String(offline.candidate_version||'—'))}" in ui
    assert "Nezávislé hodnotenie:" in ui
    assert "Identifikátor modelu:" in ui
    assert "String(offline.candidate_release_tag||\'—\')" in ui
    assert "Model 7.1.1 · čaká na tréning" in ui
    assert "const offline=d.offline_candidate;" in ui


if __name__ == "__main__":
    unittest.main()
