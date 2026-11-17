"""PropLine evening collector: offline invariants."""
from __future__ import annotations

from datetime import date, datetime, timezone
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from propline_evening_odds import collect, _price, _single_book_quotes

NOW = datetime(2026, 11, 17, 22, 0, tzinfo=timezone.utc)
DAY = date(2026, 11, 18)


def example():
    return {"events": [{
        "id": "1234", "home_team": "Alexander Zverev",
        "away_team": "Ben Shelton", "commence_time": "2026-11-18T12:00:00Z",
        "sport_title": "ATP Finals",
        "bookmakers": [{
            "key": "napoleon",
            "markets": [{"key": "player_aces", "last_update": NOW.isoformat(),
                         "outcomes": [
                             {"description": "Alexander Zverev", "name": "10+ Aces",
                              "price": -133},
                             {"description": "Alexander Zverev", "name": "11+ Aces",
                              "price": 120},
                             {"description": "Ben Shelton", "name": "Over",
                              "point": 10.5, "price": -110},
                             {"description": "Ben Shelton", "name": "Under",
                              "point": 10.5, "price": -105},
                         ]}]} ,{
            "key": "sleeper",
            "markets": [{"key": "player_aces", "outcomes": [
                {"description": "Alexander Zverev", "name": "Over",
                 "point": 10.5, "price": 110},
                {"description": "Alexander Zverev", "name": "Under",
                 "point": 10.5, "price": -110},
            ]}]}],
    }]}


def research(payload=None, *, now=NOW, day=DAY):
    return collect(day, now=now, get=lambda: (payload if payload is not None else example(), 455))


class PropLineEvening(unittest.TestCase):
    def test_retains_outer_schema_and_real_provenance(self):
        r = research()
        self.assertEqual((r["schema"], r["source"], r["target_betting_day"]),
                         (1, "propline_free", "2026-11-18"))
        self.assertEqual((r["probed_urls"], r["probed_events"],
                          r["provider_requests"], r["provider_paid_calls"]), (1, 1, 1, 0))
        self.assertEqual((r["cdb_writes"], r["published_picks_changed"]), (0, 0))
        self.assertEqual(len(r["events_in_target_window"]), 1)
        self.assertEqual(len(r["observed_prematch_priced_events"]), 1)
        self.assertEqual(r["events_in_target_window"][0]["provider"], "propline")
        self.assertEqual(r["events_in_target_window"][0]["provider_raw_event"], example()["events"][0])

    def test_sportsbook_milestones_with_correct_line_and_book(self):
        r = research()
        self.assertEqual(r["milestone_quotes"], 2)
        groups = r["events_in_target_window"][0]["aces_markets"]
        milestone = next(m for m in groups if m["kind"] == "player_aces_milestone")
        self.assertEqual(milestone["bookmaker"], "napoleon")
        self.assertEqual(milestone["verified_pairs"], [])
        values = milestone["verified_single_prices"]
        self.assertEqual([(v["threshold"], v["equivalent_over_line"])
                          for v in values], [(10, 9.5), (11, 10.5)])
        self.assertAlmostEqual(values[0]["odds"], 1 + 100/133, places=5)
        self.assertEqual(values[1]["odds"], 2.2)

    def test_full_two_way_only_from_same_sportsbook(self):
        r = research()
        self.assertEqual(r["exact_aces_pairs"], 1)
        bookmaker = next(m for m in r["events_in_target_window"][0]["aces_markets"]
                         if m["kind"] == "player_aces_ou")
        self.assertEqual(bookmaker["bookmaker"], "napoleon")
        self.assertEqual(bookmaker["verified_pairs"][0]["player"], "Ben Shelton")
        self.assertEqual(bookmaker["verified_pairs"][0]["line"], 10.5)

    def test_dfs_kept_but_never_issued_as_bookmaker_quote(self):
        r = research()
        self.assertEqual(r["dfs_pairs"], 1)
        dfs = next(m for m in r["events_in_target_window"][0]["aces_markets"]
                   if m["kind"] == "dfs_pickem_player_aces_ou")
        self.assertEqual(dfs["bookmaker"], "sleeper")
        self.assertEqual(dfs["verified_pairs"], [])
        self.assertEqual(len(dfs["research_pairs"]), 1)

    def test_one_sided_across_bookmakers_never_pooled(self):
        data = example()
        group = data["events"][0]["bookmakers"][0]["markets"][0]["outcomes"]
        group[:] = [o for o in group if o["name"] != "Under"]
        r = research(data)
        self.assertEqual(r["exact_aces_pairs"], 0)
        self.assertEqual(r["dfs_pairs"], 1)

    def test_fake_duplicate_side_does_not_count_as_two_way(self):
        data = example()
        data["events"][0]["bookmakers"][0]["markets"][0]["outcomes"].append({
            "description": "Ben Shelton", "name": "Over", "point": 10.5,
            "price": -110})
        r = research(data)
        self.assertEqual(r["exact_aces_pairs"], 0)

    def test_only_future_matches_in_target_are_eligible(self):
        data = example()
        old = dict(data["events"][0], id="1235",
                   commence_time="2026-11-17T17:00:00Z")
        outside = dict(data["events"][0], id="1236",
                       commence_time="2026-11-19T12:00:00Z")
        data["events"].extend([old, outside])
        r = research(data)
        self.assertEqual(len(r["events_in_target_window"]), 1)
        self.assertEqual(r["out_of_target_window_events"], 2)
        self.assertGreater(r["observed_prematch_priced_singles"], r["milestone_quotes"])
        self.assertEqual(r["observed_priced_singles_outside_target"], 2)

    def test_same_day_and_finished_dates_rejected(self):
        with self.assertRaises(ValueError):
            research(day=date(2026, 11, 17))
        with self.assertRaises(ValueError):
            research(day=date(2026, 11, 16))

    def test_invalid_american_and_nonnumeric_prices_rejected(self):
        self.assertIsNone(_price(0))
        self.assertIsNone(_price(float("nan")))
        self.assertIsNone(_price(True))
        self.assertIsNone(_price("-99"))
        self.assertEqual(_price(100), 2.0)
        self.assertEqual(_price(-100), 2.0)

    def test_more_aces_three_way_rejected(self):
        data = example()
        data["events"][0]["bookmakers"][0]["markets"].append({
            "key": "most_aces", "outcomes": [
                {"name": "Alexander Zverev", "price": 120},
                {"name": "Ben Shelton", "price": 140},
                {"name": "Tie", "price": 1200},
            ],
        })
        r = research(data)
        self.assertEqual(sum(len(m["verified_pairs"]) for e in r["events_in_target_window"]
                             for m in e["aces_markets"] if m["kind"] == "most_aces_match"), 0)

    def test_valid_bookmaker_most_aces_two_way_kept_as_research(self):
        data = example()
        data["events"][0]["bookmakers"][0]["markets"].append({
            "key": "most_aces", "outcomes": [
                {"name": "Alexander Zverev", "price": -120},
                {"name": "Ben Shelton", "price": 100},
            ],
        })
        r = research(data)
        self.assertEqual(r["exact_aces_pairs"], 2)
        most = next(m for m in r["events_in_target_window"][0]["aces_markets"]
                    if m["kind"] == "most_aces_match")
        self.assertEqual(most["verified_pairs"][0]["settlement"],
                         "bookmaker_rules_not_yet_verified")

    def test_most_aces_set_specific_is_not_full_match(self):
        data = example()
        data["events"][0]["bookmakers"][0]["markets"].append({
            "key": "most_aces_first_set", "outcomes": [
                {"name": "Alexander Zverev", "price": -120},
                {"name": "Ben Shelton", "price": 100},
            ],
        })
        r = research(data)
        self.assertEqual(r["exact_aces_pairs"], 1)
        self.assertFalse(any(m["kind"] == "most_aces_match"
                             for e in r["events_in_target_window"]
                             for m in e["aces_markets"]))

    def test_price_research_contains_no_source_secrets(self):
        r = research()
        import json
        body = json.dumps(r, ensure_ascii=False)
        self.assertNotIn("X-API-Key", body)
        self.assertNotIn("Bearer ", body)
        self.assertNotIn("secret", body.lower())

    def test_full_single_response_not_cut_off_at_legacy_60(self):
        original = example()["events"][0]
        payload = {"events": [dict(original, id=str(3000 + i))
                              for i in range(85)]}
        result = research(payload)
        self.assertEqual(result["candidate_events"], 85)
        self.assertEqual(result["probed_events"], 85)
        self.assertFalse(result["coverage_truncated"])
        self.assertEqual(result["provider_requests"], 1)

    def test_explicit_debug_limit_is_counted_as_truncation(self):
        original = example()["events"][0]
        payload = {"events": [dict(original, id=str(3000 + i))
                              for i in range(7)]}
        result = collect(DAY, max_events=2, now=NOW,
                         get=lambda: (payload, 455))
        self.assertEqual(result["candidate_events"], 7)
        self.assertEqual(result["probed_events"], 2)
        self.assertTrue(result["coverage_truncated"])

    def test_empty_ace_market_is_true_zero(self):
        data = example()
        data["events"][0]["bookmakers"] = []
        r = research(data)
        self.assertEqual((r["exact_aces_pairs"], r["milestone_quotes"], r["dfs_pairs"]),
                         (0, 0, 0))
        self.assertEqual(r["status"], "no_exact_aces_market_available")


if __name__ == "__main__":
    unittest.main()
