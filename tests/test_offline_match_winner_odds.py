import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from tbt.data.offline_odds import (  # noqa: E402
    candidate_link,
    decimal_odds,
    fair_market,
    legacy_name_matches,
    pair_orientation,
    parse_legacy_row,
    tournament_score,
)


class OfflineOddsTests(unittest.TestCase):
    def test_abbreviated_wta_names(self):
        self.assertTrue(legacy_name_matches("Hingis M.", "Martina Hingis"))
        self.assertTrue(
            legacy_name_matches("Medina Garrigues A.", "Anabel Medina Garrigues")
        )
        self.assertTrue(legacy_name_matches("Camerin M.E.", "Maria Elena Camerin"))
        self.assertTrue(legacy_name_matches("Williams S.", "Serena Williams"))
        self.assertFalse(legacy_name_matches("Williams S.", "Venus Williams"))

    def test_pair_orientation_is_fail_closed(self):
        self.assertEqual(
            pair_orientation(
                "Hingis M.", "Bammer S.", "Martina Hingis", "Sybil Bammer"
            ),
            "direct",
        )
        self.assertEqual(
            pair_orientation(
                "Hingis M.", "Bammer S.", "Sybil Bammer", "Martina Hingis"
            ),
            "swapped",
        )

    def test_odds_validation_and_devig(self):
        self.assertIsNone(decimal_odds("-1"))
        self.assertIsNone(decimal_odds("1.0"))
        self.assertIsNone(decimal_odds("5..5"))
        fair = fair_market(2.0, 1.72)
        self.assertAlmostEqual(
            fair["player1_implied_probability"]
            + fair["player2_implied_probability"],
            1.0,
        )
        self.assertGreater(fair["raw_overround"], 0)

    def test_legacy_row_parser(self):
        parsed = parse_legacy_row(
            {
                "Tournament": "Australian Open",
                "Date": "2026-01-20",
                "Surface": "Hard",
                "Round": "Quarterfinals",
                "Best of": "3",
                "Player_1": "Sabalenka A.",
                "Player_2": "Gauff C.",
                "Winner": "Sabalenka A.",
                "Rank_1": "1",
                "Rank_2": "3",
                "Odd_1": "1.55",
                "Odd_2": "2.45",
            },
            row_number=2,
            tour="wta",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.best_of, 3)
        self.assertEqual(parsed.odds_a, 1.55)

    def test_candidate_link_exact_identity(self):
        source = parse_legacy_row(
            {
                "Tournament": "Australian Open",
                "Date": "2026-01-20",
                "Surface": "Hard",
                "Round": "Quarterfinals",
                "Best of": "3",
                "Player_1": "Sabalenka A.",
                "Player_2": "Gauff C.",
                "Winner": "Sabalenka A.",
                "Rank_1": "1",
                "Rank_2": "3",
                "Odd_1": "1.55",
                "Odd_2": "2.45",
            },
            row_number=2,
            tour="wta",
        )
        linked = candidate_link(
            source,
            canonical_tour="wta",
            canonical_date=source.event_date,
            canonical_player1="Aryna Sabalenka",
            canonical_player2="Coco Gauff",
            canonical_winner="Aryna Sabalenka",
            canonical_tournament="Australian Open",
            canonical_surface="hard",
            canonical_round="Quarterfinals",
            canonical_best_of=3,
            canonical_rank1=1,
            canonical_rank2=3,
        )
        self.assertTrue(linked["accepted"])
        self.assertEqual(linked["market"]["player1_odds"], 1.55)

    def test_candidate_link_rejects_wrong_winner(self):
        source = parse_legacy_row(
            {
                "Tournament": "Australian Open",
                "Date": "2026-01-20",
                "Surface": "Hard",
                "Round": "Quarterfinals",
                "Best of": "3",
                "Player_1": "Sabalenka A.",
                "Player_2": "Gauff C.",
                "Winner": "Sabalenka A.",
                "Odd_1": "1.55",
                "Odd_2": "2.45",
            },
            row_number=2,
            tour="wta",
        )
        linked = candidate_link(
            source,
            canonical_tour="wta",
            canonical_date=source.event_date,
            canonical_player1="Aryna Sabalenka",
            canonical_player2="Coco Gauff",
            canonical_winner="Coco Gauff",
            canonical_tournament="Australian Open",
            canonical_surface="hard",
            canonical_round="Quarterfinals",
            canonical_best_of=3,
        )
        self.assertFalse(linked["accepted"])
        self.assertIn("winner_conflict", linked["evidence"])

    def test_tournament_tokens(self):
        score, evidence = tournament_score(
            "Western & Southern Financial Group Women's Open",
            "Western Southern Open",
        )
        self.assertGreaterEqual(score, 1)
        self.assertIn(evidence, {"tournament_exact", "tournament_tokens"})


if __name__ == "__main__":
    unittest.main()
