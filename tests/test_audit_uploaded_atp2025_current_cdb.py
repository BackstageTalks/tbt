"""Read-only Flashscore-vs-CDB audit regression checks (synthetic data)."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_uploaded_atp2025_current_cdb import verify_row, score_sets, dt


def sample():
    src = {
        "match_id": "SYNTH001",
        "winner_name": "Carreno Busta P.", "loser_name": "Shevchenko A.",
        "start_time_utc": "2024-12-27T02:10:00Z", "score": "6-2 6-1",
        "best_of": "3", "surface": "Hard", "round": "RR",
        "tourney_date": "20241227", "tourney_id": "synthetic-2024",
        "tourney_name": "Synthetic United Cup",
        "w_ace": "3", "w_df": "0", "w_svpt": "40", "w_1stIn": "27",
        "w_1stWon": "21", "w_2ndWon": "9", "w_SvGms": "8",
        "w_bpSaved": "1", "w_bpFaced": "2",
        "l_ace": "3", "l_df": "4", "l_svpt": "42", "l_1stIn": "24",
        "l_1stWon": "14", "l_2ndWon": "4", "l_SvGms": "7",
        "l_bpSaved": "2", "l_bpFaced": "7",
    }
    index = {src["match_id"]: [{
        "event_id": src["match_id"], "canonical_match_id": "synthetic-cdb-1",
        "tour": "ATP", "start_utc": src["start_time_utc"],
        "player1_source": src["winner_name"], "player2_source": src["loser_name"],
        "link": {"accepted": True, "orientation": "direct"},
    }]}
    canonical = {"synthetic-cdb-1": {
        "match_id": "synthetic-cdb-1", "tour": "atp",
        "scheduled_at": src["start_time_utc"],
        "player1_id": "provider-A", "player2_id": "provider-B",
        "player1_name": "Pablo Carreno Busta",
        "player2_name": "Aleksandr Shevchenko",
        "winner_id": "provider-A", "status": "finished",
        "surface": "Hard", "best_of": 3,
        "stats_json": json.dumps({
            "p1_set1_games": 6, "p2_set1_games": 2,
            "p1_set2_games": 6, "p2_set2_games": 1,
            "p1_aces": 3, "p2_aces": 3,
            "p1_double_faults": 0, "p2_double_faults": 4,
        }),
    }}
    return src, index, canonical


class FlashscoreCurrentCDBAudit(unittest.TestCase):
    def test_even_full_corroboration_is_not_import_authorization(self):
        source, index, canonical = sample()
        status, missing = verify_row(source, index, canonical)
        self.assertEqual(status, "research_corrob_only_missing_independent_id_witness")
        self.assertGreater(missing, 0)

    def test_index_absent(self):
        source, _, canonical = sample()
        self.assertEqual(verify_row(source, {}, canonical),
                         ("flashscore_event_index_absent", 0))

    def test_native_event_id_collision(self):
        source, index, canonical = sample()
        index[source["match_id"]].append(dict(index[source["match_id"]][0]))
        self.assertEqual(verify_row(source, index, canonical),
                         ("flashscore_event_id_collision", 0))

    def test_utc_drift_blocks(self):
        source, index, canonical = sample()
        index[source["match_id"]][0]["start_utc"] = "2024-12-27T02:11:00Z"
        self.assertEqual(verify_row(source, index, canonical),
                         ("exact_utc_disagreement", 0))

    def test_winner_conflict_blocks(self):
        source, index, canonical = sample()
        canonical["synthetic-cdb-1"]["winner_id"] = "provider-B"
        self.assertEqual(verify_row(source, index, canonical),
                         ("canonical_winner_conflict", 0))

    def test_complete_score_required(self):
        source, index, canonical = sample()
        stats = json.loads(canonical["synthetic-cdb-1"]["stats_json"])
        stats["p1_set2_games"] = 5
        canonical["synthetic-cdb-1"]["stats_json"] = json.dumps(stats)
        self.assertEqual(verify_row(source, index, canonical),
                         ("canonical_full_set_score_absent_or_conflict", 0))

    def test_existing_nonnull_stat_conflict_not_overwritten(self):
        source, index, canonical = sample()
        stats = json.loads(canonical["synthetic-cdb-1"]["stats_json"])
        stats["p1_return_points_won"] = 0.99
        canonical["synthetic-cdb-1"]["stats_json"] = json.dumps(stats)
        self.assertEqual(verify_row(source, index, canonical),
                         ("other_cdb_stat_conflict", 0))

    def test_tiebreak_and_incomplete_score(self):
        self.assertEqual(score_sets("7-6(4) 6-4"), [(7, 6), (6, 4)])
        self.assertIsNone(score_sets("7-6 6-4 RET"))
        self.assertIsNone(dt("2025-01-01T12:00:00"))


if __name__ == "__main__":
    unittest.main()
