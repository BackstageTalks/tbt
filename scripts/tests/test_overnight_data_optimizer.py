from __future__ import annotations
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from overnight_data_optimizer import budget, useful_gain, next_quota_probe_after_reset

class NightlySafetyTests(unittest.TestCase):
    def test_never_infer_unknown_quota(self):
        self.assertEqual(budget(None, 0, max_spend=6000, reserve=1200), 0)
    def test_preserve_serving_reserve(self):
        self.assertEqual(budget(1300, 0, max_spend=6000, reserve=1200), 100)
        self.assertEqual(budget(1200, 0, max_spend=6000, reserve=1200), 0)
    def test_hard_global_cap(self):
        self.assertEqual(budget(15000, 900, max_spend=6000, reserve=1200), 5100)
        self.assertEqual(budget(15000, 6000, max_spend=6000, reserve=1200), 0)
    def test_probe_is_1711_utc_across_summer_winter_switch(self):
        zone = ZoneInfo("Europe/Bratislava")
        for day in ((2026, 10, 25), (2027, 3, 28), (2027, 7, 1)):
            before = datetime(*day, 17, 8, tzinfo=timezone.utc)
            probe = next_quota_probe_after_reset(before)
            self.assertEqual((probe.hour, probe.minute), (17, 11))
            local = probe.astimezone(zone)
            expected_hour = 18 if local.utcoffset().total_seconds() == 3600 else 19
            self.assertEqual((local.hour, local.minute), (expected_hour, 11))
            after = datetime(*day, 17, 12, tzinfo=timezone.utc)
            self.assertEqual(next_quota_probe_after_reset(after),
                             probe + timedelta(days=1))
        with self.assertRaises(ValueError):
            next_quota_probe_after_reset(datetime(2026, 10, 25, 17, 8))

    def test_count_only_is_not_quality(self):
        old={"both_players_quality_ready":18000,"any_stats_matches":85000}
        new={"both_players_quality_ready":18000,"any_stats_matches":85400}
        self.assertEqual(useful_gain(old,new),{"both_quality":0,"any_stats":400})

if __name__ == "__main__":
    unittest.main()
