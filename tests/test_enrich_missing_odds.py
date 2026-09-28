"""Unit checks for precise odds recovery contract extraction."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from enrich_missing_odds import contract, enrich


class OddsRecoveryContracts(unittest.TestCase):
    def test_set_threshold_from_selection(self):
        self.assertEqual(contract({"market": "sets", "selection_id": "sets:under:2.5"}),
                         ("total_sets", "under", 2.5, "exact_market_and_line"))

    def test_games_model_baseline_is_not_market_line(self):
        kind, direction, line, precision = contract({
            "market": "games", "selection_id": "games:high",
            "reference_projection": 23.45,
        })
        self.assertEqual((kind, direction, line, precision),
                         ("total_games", "high", None, "bookmaker_line_unknown"))

    def test_aces_is_head_to_head_not_total(self):
        self.assertEqual(contract({"market": "aces", "selection_id": "345"}),
                         ("most_aces", "selected_player_more_than_opponent",
                          None, "exact_market_type"))

    def test_existing_real_price_inventory_separate(self):
        row = {"event_id": "777", "scheduled_at": "2026-09-21T10:00:00+00:00",
               "player1": {"name": "A"}, "player2": {"name": "B"},
               "market_publications": [
                   {"market": "sets", "section": "sets", "selection": "Under 2.5 Sets",
                    "selection_id": "sets:under:2.5", "price_status": "projection_only",
                    "publication_key": "sets:777", "issued_at": "2026-09-21T08:00:00+00:00",
                    "projection": 2.28, "reference_projection": 2.5},
                   {"market": "aces", "section": "ace", "selection": "A",
                    "selection_id": "100", "odds": 1.72,
                    "price_status": "priced_projection",
                    "issued_at": "2026-09-21T08:00:00+00:00"},
               ]}
        rows, audit = enrich([row])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["line"], 2.5)
        self.assertEqual(rows[0]["model_projection"], 2.28)
        self.assertEqual(audit["authentic_priced_by_market"]["aces"], 1)


if __name__ == "__main__":
    unittest.main()
