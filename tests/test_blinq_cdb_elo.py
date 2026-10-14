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

    def test_end_to_end_all_78_canonical_partitions(self):
        import hashlib
        import json
        import tempfile
        from pathlib import Path
        import pandas as pd
        from build_blinq_cdb_elo import build

        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch) / "cdb"
            output = Path(scratch) / "elo"
            root.mkdir()
            years = {}
            for year in range(1949, 2027):
                path = root / f"history-{year}.parquet"
                pd.DataFrame([{
                    "match_id": f"match-{year}", "tour": "atp",
                    "scheduled_at": datetime(year, 6, 1, 11, tzinfo=timezone.utc),
                    "player1_id": "a", "player1_name": "A",
                    "player2_id": "b", "player2_name": "B",
                    "winner_id": "a", "surface": "clay",
                    "tournament_level": "ATP 250", "status": "completed",
                }]).to_parquet(path, index=False)
                years[str(year)] = {
                    "asset": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            (root / "history_manifest.json").write_text(json.dumps({"years": years}))
            report = build(
                root, output, app_sha="synthetic-test",
                cutoff=datetime(2027, 1, 1, tzinfo=timezone.utc),
                min_input_matches=78,
            )
            self.assertEqual(report["canonical_input_matches"], 78)
            self.assertEqual(report["eligible_completed_matches"], 78)
            self.assertEqual(len(report["year_partitions"]), 78)
            self.assertEqual(report["canonical_cdb_writes"], 0)
            first = pd.read_parquet(output / "elo-history-1949.parquet")
            self.assertEqual(first.iloc[0]["p1_elo_pre"], 1500.0)
            last = pd.read_parquet(output / "elo-history-2026.parquet")
            self.assertGreater(last.iloc[0]["p1_elo_pre"], 1500.0)




    def test_ta_heuristic_is_not_proven_crosswalk(self):
        from compare_blinq_elo_ta import compare
        own = [{"tour": "atp", "name": "Sinner J.", "elo": 2200.0},
               {"tour": "atp", "name": "Djokovic N.", "elo": 2150.0}]
        ta = [{"tour": "atp", "name": "Jannik Sinner", "elo": 2300.0},
              {"tour": "atp", "name": "Novak Djokovic", "elo": 2100.0}]
        result = compare(own, ta, "atp")
        self.assertEqual(result["unique_heuristic_name_matches"], 2)
        self.assertFalse(result["identity_crosswalk_verified"])
        self.assertEqual(result["comparison_status"], "insufficient_heuristic_overlap")

    def test_ta_ambiguous_names_are_quarantined(self):
        from compare_blinq_elo_ta import compare
        own = [{"tour": "atp", "name": "Sinner J.", "elo": 2200.0},
               {"tour": "atp", "name": "Sinner J.", "elo": 2190.0}]
        ta = [{"tour": "atp", "name": "Jannik Sinner", "elo": 2300.0}]
        result = compare(own, ta, "atp")
        self.assertEqual(result["unique_heuristic_name_matches"], 0)
        self.assertEqual(result["blinq_name_collisions_excluded"], 2)


if __name__ == "__main__":
    unittest.main()
