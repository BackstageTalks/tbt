import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from link_uploaded_flashscore_verified import norm, short_matches, score_two_sets, utc


class FlashscoreExactGateTests(unittest.TestCase):
    def test_abbreviated_player_requires_first_initial_and_full_surname(self):
        self.assertTrue(short_matches("Pablo Carreño Busta", "Carreno-Busta P."))
        self.assertTrue(short_matches("Yosuke Watanuki", "Watanuki Y."))
        self.assertFalse(short_matches("Pablo Carreno Busta", "Carreno-Busta J."))
        self.assertFalse(short_matches("Pablo Carreno Busta", "Carreno P."))
        self.assertFalse(short_matches("Pablo Carreno Busta", "Busta P."))

    def test_two_complete_winner_first_sets_only(self):
        self.assertEqual(score_two_sets("6-2 7-6"), [(6, 2), (7, 6)])
        self.assertIsNone(score_two_sets("6-2 3-6 7-5"))
        self.assertIsNone(score_two_sets("6-2 4-4"))
        self.assertIsNone(score_two_sets("6-6 6-2"))
        self.assertIsNone(score_two_sets("RET"))

    def test_exact_clock_never_uses_date_only(self):
        self.assertEqual(utc("2026-10-12T12:00:00Z"), utc("2026-10-12T14:00:00+02:00"))
        self.assertNotEqual(utc("2026-10-12T12:00:00Z"),utc("2026-10-12T12:01:00Z"))
        self.assertIsNone(utc("2026-10-12 12:00:00"))

    def test_unicode(self):
        self.assertEqual(norm("Carreño-Busta P."), norm("Carreno Busta P"))


if __name__ == "__main__":
    unittest.main()
