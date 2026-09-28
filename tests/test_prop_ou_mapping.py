"""Pure model-to-PropLine O/U mapping regression tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from tbt.services.prop_ou_mapping import best_ou_option, prop_ou_candidates


class TestPropOverUnder(unittest.TestCase):
    def test_games_market_real_odds_and_model_line(self):
        card = {"market": "games", "projection": 25.0,
                "projection_uncertainty": 3.5, "best_of": 3}
        payload = {"bookmakers": [
            {"title": "DemoBook", "markets": [{"key": "totals", "outcomes": [
                {"name": "Over", "point": 22.5, "price": 1.90},
                {"name": "Under", "point": 22.5, "price": 1.92},
            ]}]}
        ]}
        result = prop_ou_candidates(card, payload)
        self.assertEqual(len(result), 2)
        over = next(x for x in result if x["side"] == "over")
        under = next(x for x in result if x["side"] == "under")
        self.assertEqual(over["odds"], 1.90)
        self.assertGreater(over["model_probability"], 0.5)
        self.assertLess(under["model_probability"], 0.5)

    def test_player_aces_filters_to_correct_person(self):
        card = {"market": "aces", "projection": 7.2,
                "selection": "Alice", "projection_subject": "Alice"}
        payload = {"bookmakers": [{"key": "book", "markets": [
            {"key": "player_aces", "outcomes": [
                {"name": "Over", "description": "Alice", "point": 5.5, "price": 1.80},
                {"name": "Under", "description": "Alice", "point": 5.5, "price": 2.00},
                {"name": "Over", "description": "Bob", "point": 4.5, "price": 1.75},
            ]}]}]}
        rows = prop_ou_candidates(card, payload)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["line"] == 5.5 for r in rows))

    def test_sets_reject_unmodeled_lines(self):
        card = {"market": "sets", "best_of": 3, "projection": 2.7,
                "evidence_adjusted_probability": 0.72}
        payload = {"bookmakers": [{"key": "book", "markets": [
            {"key": "total_sets", "outcomes": [
                {"name": "Over 2.5", "price": 2.0},
                {"name": "Under 2.5", "price": 1.8},
                {"name": "Over 3.5", "price": 3.0},
            ]}]}]}
        rows = prop_ou_candidates(card, payload)
        self.assertEqual(len(rows), 2)
        over = next(x for x in rows if x["side"] == "over")
        self.assertEqual(over["model_probability"], 0.72)
        self.assertEqual(over["odds"], 2.0)

    def test_no_fake_prices_or_unknown_market(self):
        card = {"market": "double_faults", "projection": 3.2,
                "projection_subject": "Alice"}
        self.assertEqual(prop_ou_candidates(card, {"bookmakers": []}), [])
        self.assertIsNone(best_ou_option(card, {"bookmakers": []}))

    def test_matched_books_not_mix_lines(self):
        card = {"market": "games", "projection": 27, "projection_uncertainty": 4}
        payload = {"bookmakers": [
            {"key": "bookA", "markets": [{"key": "totals", "outcomes": [
                {"name": "Over", "point": 24.5, "price": 1.80}]}]},
            {"key": "bookB", "markets": [{"key": "totals", "outcomes": [
                {"name": "Over", "point": 25.5, "price": 2.0}]}]}
        ]}
        self.assertEqual(len(prop_ou_candidates(card, payload)), 2)


if __name__ == "__main__":
    unittest.main()
