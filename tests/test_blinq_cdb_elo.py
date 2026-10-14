import math
import unittest
from datetime import datetime, timezone

from tbt.models.feature_builder import FeatureBuilder
from tbt.schemas import MatchRecord
from build_blinq_cdb_elo import pre_match, replay_day, utc


def match(mid, year, day, first, second, winner, surface="hard"):
    return MatchRecord(
        match_id=mid,
        tour="atp",
        scheduled_at=datetime(year, 1, day, 13, tzinfo=timezone.utc),
        player1_id=first,
        player1_name=first,
        player2_id=second,
        player2_name=second,
        winner_id=winner,
        surface=surface,
        tournament_level="ATP 250",
        status="completed",
    )


class CanonicalEloParityTest(unittest.TestCase):
    def test_pre_matches_production_feature_builder_snapshot(self):
        x = match("x", 2024, 2, "a", "b", "a")
        b = FeatureBuilder()
        pre = pre_match(x, b)
        features = b.snapshot(x)
        self.assertAlmostEqual(pre["p1_expected_win_pre"], features["elo_probability"])
        self.assertAlmostEqual(
            (pre["p1_elo_pre"] - pre["p2_elo_pre"]) / 400.0,
            features["elo_diff"],
        )
        self.assertEqual((pre["p1_elo_pre"], pre["p2_elo_pre"]), (1500.0, 1500.0))
        self.assertEqual(pre["p1_yelo_matches_pre"], 0)
        b.update(x)
        next_pre = pre_match(match("y", 2024, 3, "a", "b", "b"), b)
        self.assertGreater(next_pre["p1_elo_pre"], 1500)
        self.assertLess(next_pre["p2_elo_pre"], 1500)
        self.assertAlmostEqual(
            next_pre["p1_expected_win_pre"],
            b.snapshot(match("y", 2024, 3, "a", "b", "b"))["elo_probability"],
        )

    def test_simultaneous_same_day_prevents_leakage(self):
        matches = [
            match("x", 2024, 2, "a", "b", "a"),
            match("y", 2024, 2, "a", "c", "a"),
        ]
        b = FeatureBuilder()
        rows, names = [], {}
        replay_day(matches, b, rows, names)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["p1_elo_pre"], 1500)
        self.assertEqual(rows[1]["p1_elo_pre"], 1500)
        self.assertEqual(rows[0]["p1_matches_pre"], 0)
        self.assertEqual(rows[1]["p1_matches_pre"], 0)
        self.assertEqual(b.players["atp:a"].matches, 2)
        self.assertGreater(b.players["atp:a"].overall_elo, 1500)

    def test_surface_and_year_reset_follow_production(self):
        b = FeatureBuilder()
        b.update(match("x", 2023, 2, "a", "b", "a", surface="clay"))
        first_2024 = match("y", 2024, 3, "a", "b", "a", surface="hard")
        pre = pre_match(first_2024, b)
        self.assertEqual(pre["p1_yelo_pre"], 1500.0)
        self.assertEqual(pre["p1_yelo_matches_pre"], 0)
        self.assertGreater(pre["p1_elo_pre"], 1500.0)
        self.assertAlmostEqual(pre["p1_surface_elo_pre"], pre["p1_elo_pre"])

    def test_utc_and_probability_bounds(self):
        self.assertEqual(utc("2024-05-02T02:30:00+02:00").hour, 0)
        b = FeatureBuilder()
        v = pre_match(match("first", 2021, 2, "a", "b", "a"), b)
        self.assertTrue(math.isfinite(v["p1_elo_pre"]))
        self.assertTrue(0.0 < v["p1_expected_win_pre"] < 1.0)


if __name__ == "__main__":
    unittest.main()
