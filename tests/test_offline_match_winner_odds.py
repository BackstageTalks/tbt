import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from tbt.data.provider_context import minimize_provider_payload  # noqa: E402
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

    def test_winner_loser_tennis_data_row_parser(self):
        parsed = parse_legacy_row(
            {
                "Tournament": "Brisbane International",
                "Date": "2013-01-01",
                "Surface": "Hard",
                "Round": "1st Round",
                "Best of": "3",
                "Winner": "Istomin D.",
                "Loser": "Klizan M.",
                "WRank": "43",
                "LRank": "30",
                "B365W": "1.9",
                "B365L": "1.8",
                "PSW": "1.88",
                "PSL": "2.0",
                "AvgW": "1.88",
                "AvgL": "1.85",
                "MaxW": "2.05",
                "MaxL": "2.0",
            },
            row_number=2,
            tour="atp",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.player_a, "Istomin D.")
        self.assertEqual(parsed.player_b, "Klizan M.")
        self.assertEqual(parsed.rank_a, 43)
        self.assertEqual(parsed.rank_b, 30)
        self.assertEqual(parsed.odds_a, 1.9)
        self.assertEqual(parsed.odds_b, 1.8)

    def test_winner_loser_parser_falls_back_to_avg_not_max(self):
        parsed = parse_legacy_row(
            {
                "Tournament": "Example",
                "Date": "2026-01-01",
                "Surface": "Hard",
                "Round": "1st Round",
                "Best of": "3",
                "Winner": "Player A",
                "Loser": "Player B",
                "WRank": "10",
                "LRank": "20",
                "B365W": "",
                "B365L": "",
                "PSW": "",
                "PSL": "",
                "AvgW": "1.7",
                "AvgL": "2.1",
                "MaxW": "1.95",
                "MaxL": "2.4",
            },
            row_number=3,
            tour="atp",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.odds_a, 1.7)
        self.assertEqual(parsed.odds_b, 2.1)

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

    def test_provider_context_preserves_compact_market_marker(self):
        payload = {
            "_tbt_match_winner_odds": {
                "schema": 1,
                "status": "linked",
                "source": "operator_wta_txt",
                "source_match_id": "abc123",
                "source_file_sha256": "deadbeef",
                "price_kind": "historical_two_way_unspecified_timestamp",
                "player1_odds": 1.55,
                "player2_odds": 2.45,
                "player1_implied_probability": 0.6125,
                "player2_implied_probability": 0.3875,
                "raw_overround": 0.053,
                "should_drop": "raw-noise",
            }
        }
        compact = minimize_provider_payload(payload)
        marker = compact["_tbt_match_winner_odds"]
        self.assertEqual(marker["source"], "operator_wta_txt")
        self.assertNotIn("should_drop", marker)

    def test_tournament_tokens(self):
        score, evidence = tournament_score(
            "Western & Southern Financial Group Women's Open",
            "Western Southern Open",
        )
        self.assertGreaterEqual(score, 1)
        self.assertIn(evidence, {"tournament_exact", "tournament_tokens"})


if __name__ == "__main__":
    unittest.main()
