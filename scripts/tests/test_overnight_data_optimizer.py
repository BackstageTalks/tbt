from __future__ import annotations
import unittest
from overnight_data_optimizer import budget, useful_gain

class NightlySafetyTests(unittest.TestCase):
    def test_never_infer_unknown_quota(self):
        self.assertEqual(budget(None, 0, max_spend=6000, reserve=1200), 0)
    def test_preserve_serving_reserve(self):
        self.assertEqual(budget(1300, 0, max_spend=6000, reserve=1200), 100)
        self.assertEqual(budget(1200, 0, max_spend=6000, reserve=1200), 0)
    def test_hard_global_cap(self):
        self.assertEqual(budget(15000, 900, max_spend=6000, reserve=1200), 5100)
        self.assertEqual(budget(15000, 6000, max_spend=6000, reserve=1200), 0)
    def test_count_only_is_not_quality(self):
        old={"both_players_quality_ready":18000,"any_stats_matches":85000}
        new={"both_players_quality_ready":18000,"any_stats_matches":85400}
        self.assertEqual(useful_gain(old,new),{"both_quality":0,"any_stats":400})

if __name__ == "__main__":
    unittest.main()
