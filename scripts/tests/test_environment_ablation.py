"""Lightweight mocked smoke tests for the matched Environment ablation."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from audit_static_environment_ablation import compare, split_dates
from tbt.models.feature_builder import FEATURE_NAMES


class EnvironmentAblationTests(unittest.TestCase):
    def fixture(self):
        rng = np.random.default_rng(42)
        rows = []
        for day in range(40):
            for index in range(12):
                features = {name: 0.0 for name in FEATURE_NAMES}
                signal = rng.standard_normal()
                features["travel_km_advantage"] = signal
                features["environment_known"] = float(index % 3 != 0)
                features["weather_serve_interaction"] = 999.0
                features["weather_known"] = 1.0
                features["serve_quality_diff"] = 999.0
                features["elo_probability"] = 0.5
                rows.append({
                    **features,
                    "target": int(signal > 0),
                    "scheduled_at": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=day),
                    "match_id": f"{day}-{index}",
                })
        return pd.DataFrame(rows)

    def test_no_day_leakage_and_matched_holdout(self):
        frame = self.fixture()
        train, test, cutoff = split_dates(frame)
        self.assertEqual(int(train.sum()) + int(test.sum()), len(frame))
        self.assertNotEqual(
            set(frame.loc[train, "scheduled_at"]) & set(frame.loc[test, "scheduled_at"]),
            set(frame.loc[train, "scheduled_at"]),
        )
        self.assertTrue(cutoff)
        report = compare(frame)
        self.assertEqual(
            report["models"]["baseline"]["all_holdout"]["rows"],
            report["models"]["plus_static_environment"]["all_holdout"]["rows"],
        )
        self.assertNotIn("travel_km_advantage", report["base_features"])
        self.assertIn("travel_km_advantage", report["added_static_environment_features"])
        self.assertNotIn("weather_serve_interaction", report["base_features"])
        self.assertNotIn("serve_quality_diff", report["base_features"])
        self.assertLess(
            report["models"]["plus_static_environment"]["all_holdout"]["log_loss"],
            report["models"]["baseline"]["all_holdout"]["log_loss"],
        )

    def test_too_few_dates_fails(self):
        frame = self.fixture()
        with self.assertRaisesRegex(ValueError, "30 distinct"):
            split_dates(frame.iloc[:20])

    def test_missing_feature_fails_closed(self):
        frame = self.fixture().drop(columns=["travel_km_advantage"])
        with self.assertRaisesRegex(ValueError, "missing feature columns"):
            compare(frame)


if __name__ == "__main__":
    unittest.main()
