import importlib.util
import io
import json
import unittest
from datetime import datetime, timezone
from unittest import mock
from urllib.error import HTTPError
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "closeout", Path(__file__).resolve().parents[1] / "scripts/propline_nightly_closeout.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CloseoutContractTests(unittest.TestCase):
    def setUp(self):
        mod.STATE.update(calls=0, remaining=None, reason="", batches=0)
        mod.DATA.clear()

    def test_utc_cutoff_excludes_new_quota(self):
        self.assertTrue(mod.allowed(datetime(2026, 10, 10, 21, 0, tzinfo=timezone.utc)))
        self.assertTrue(mod.allowed(datetime(2026, 10, 10, 22, 0, tzinfo=timezone.utc)))
        self.assertFalse(mod.allowed(datetime(2026, 10, 10, 23, 55, tzinfo=timezone.utc)))
        self.assertFalse(mod.allowed(datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)))

    def test_git_blob_sha_uses_nul_byte(self):
        import hashlib
        payload = b"test"
        expected = hashlib.sha1(b"blob 4" + bytes([0]) + payload).hexdigest()
        self.assertEqual(mod.blob_sha(payload), expected)

    def test_capped_before_provider_request(self):
        with mock.patch.object(mod, "MAX_CALLS", 750), mock.patch.object(mod, "now", return_value=datetime(2026, 10, 10, 22, tzinfo=timezone.utc)), mock.patch.object(mod.urllib.request, "urlopen", side_effect=AssertionError("No outbound call")):
            mod.STATE["calls"] = 750
            self.assertIsNone(mod.request("/sports/tennis/events"))
            self.assertEqual(mod.STATE["reason"], "run_cap")

    def test_exhausted_provider_quota_stops(self):
        with mock.patch.object(mod, "now", return_value=datetime(2026, 10, 10, 22, tzinfo=timezone.utc)), mock.patch.object(mod.urllib.request, "urlopen", side_effect=AssertionError("No outbound call")):
            mod.STATE["remaining"] = 0
            self.assertIsNone(mod.request("/sports/tennis/events"))
            self.assertEqual(mod.STATE["reason"], "daily_quota_exhausted")


    def test_unique_priced_tennis_markets_prioritized_over_generic_odds(self):
        self.assertEqual(
            mod.SPECIAL_MARKETS,
            ("player_break_points_won", "total_tiebreaks", "total_aces",
             "player_games_won"),
        )
        self.assertTrue(set(mod.SPECIAL_MARKETS).issubset(mod.MARKETS))
        self.assertLess(mod.odds_priority({"player_break_points_won"}),
                        mod.odds_priority({"player_aces"}))
        self.assertLess(mod.odds_priority({"total_tiebreaks"}),
                        mod.odds_priority({"h2h"}))
        self.assertLess(mod.odds_priority({"total_aces"}),
                        mod.odds_priority({"totals"}))
        self.assertEqual(mod.odds_priority(set()), len(mod.MARKETS))
        self.assertEqual(mod.MAX_CALLS, 750)

    def test_night_only_closeout_requests_all_advertised_niche_props_in_one_odds_call(self):
        utc = datetime(2026, 10, 11, 21, 0, tzinfo=timezone.utc)
        paths = []
        niche = {"player_break_points_won", "total_tiebreaks", "total_aces",
                 "player_games_won", "player_double_faults"}
        def fake_request(path, params=None):
            paths.append((path, params))
            if path == "/sports/tennis/events":
                return {"events": [
                    {"id": "101", "commence_time": "2026-10-12T01:00:00Z"},
                    {"id": "202", "commence_time": "2026-10-12T03:00:00Z"},
                ]}
            if path.endswith("/101/markets"):
                return {"markets": [{"key": "h2h"}]}
            if path.endswith("/202/markets"):
                return {"markets": [{"key": k} for k in sorted(niche)]}
            if path.endswith("/odds"):
                return {"bookmakers": []}
            raise AssertionError("Unexpected path: " + path)

        with mock.patch.object(mod, "KEY", "offline"), \
             mock.patch.object(mod, "TOKEN", "offline"), \
             mock.patch.object(mod, "now", return_value=utc), \
             mock.patch.object(mod, "request", side_effect=fake_request), \
             mock.patch.object(mod, "save"), \
             mock.patch.object(mod, "flush_if_needed"):
            mod.collect()

        odds = [(path, params) for path, params in paths if path.endswith("/odds")]
        self.assertEqual(len(odds), 2)
        self.assertEqual(odds[0][0], "/sports/tennis/events/202/odds")
        self.assertEqual(set(odds[0][1]["markets"].split(",")), niche)
        self.assertEqual(odds[1][0], "/sports/tennis/events/101/odds")
        self.assertEqual(odds[1][1]["markets"], "h2h")

    def test_save_batch_preserves_on_readback_failure(self):
        mod.DATA.append({"event_id": "123", "odds": {"bookmakers": []}})
        with mock.patch.object(mod, "github", return_value=None), mock.patch("pathlib.Path.write_bytes", return_value=1):
            with self.assertRaisesRegex(RuntimeError, "read-back FAILED"):
                mod.save("2026-10-10", "123")
        self.assertEqual(len(mod.DATA), 1)
        self.assertEqual(mod.STATE["batches"], 0)


if __name__ == "__main__":
    unittest.main()
