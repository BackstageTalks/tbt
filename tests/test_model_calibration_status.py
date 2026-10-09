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


if __name__ == "__main__":
    unittest.main()
