import copy, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from charting_cdb_final_decision import SOURCE, MATCH, EVENT, decide

def fixture():
    stats = {
        "p1_aces": 4.0, "p1_double_faults": 2.0,
        "p1_first_serve_win": .944444444444, "p1_second_serve_win": .4,
        "p1_service_points_won": .75, "p1_return_points_won": .758620689655,
        "p2_aces": 1.0, "p2_double_faults": 3.0,
        "p2_first_serve_win": .35, "p2_second_serve_win": 0.0,
        "p2_service_points_won": .241379310345, "p2_return_points_won": .25,
        "p2_break_point_serve_win": .285714285714,
    }
    witness = {
        "source_match_id": SOURCE, "canonical_candidate_id": MATCH,
        "event_identity_proven": False, "cdb_writes": 0,
        "context_link_type": "RESEARCH_TOURNAMENT_ALIAS_ONLY",
        "source_match": {"date": "20250812", "players": ["Gabriella Mikaul", "Olivia Gadecki"]},
        "missing_cells": copy.deepcopy(stats),
    }
    report = {"counts": {"context_review_candidate_rows": 1,
                         "RESEARCH_FIELD_GAPS_PENDING_EVENT_ID_PROOF": 1,
                         "missing_candidate_cells_not_approved": 13}}
    observations = [{
        "status": "RESEARCH_FIELD_GAPS_PENDING_EVENT_ID_PROOF",
        "source_match_id": SOURCE, "canonical_match_id_candidate": MATCH,
        "write_authorized": False, "missing_cells": copy.deepcopy(stats),
        "matching_existing_cells": [], "conflicting_existing_cells": []
    }]
    canonical = {
        "match_id": MATCH, "player1_id": "232651", "player2_id": "1044682",
        "winner_id": "232651", "provider_context_json": {"_tbt_provider_event_id": EVENT},
        "stats_json": {}
    }
    return witness, report, observations, canonical, "a" * 64, "b" * 64


class FinalGateTests(unittest.TestCase):
    def test_full_match_discrepancy_blocks_all_13(self):
        out = decide(*fixture())
        self.assertEqual(out["cells_written"], 0)
        self.assertEqual(out["cells_authorized"], 0)
        self.assertEqual(out["unapproved_candidate_cells"], 13)
        self.assertTrue(any(c["field"] == "p1_aces" for c in out["independent_conflicts"]))
        self.assertEqual(out["charted_serve_points"], {"olivia_gadecki": 28, "gabriella_mikaul": 29})
    def test_refuses_false_identity_attestation(self):
        args = list(fixture()); args[0]["event_identity_proven"] = True
        with self.assertRaises(ValueError): decide(*args)
    def test_refuses_source_witness_drift(self):
        args = list(fixture()); args[0]["missing_cells"]["p1_aces"] = 10
        with self.assertRaises(ValueError): decide(*args)
    def test_refuses_extra_unreviewed_rows(self):
        args = list(fixture()); args[2].append(dict(args[2][0]))
        with self.assertRaises(ValueError): decide(*args)
    def test_refuses_canonical_provider_id_drift(self):
        args = list(fixture()); args[3]["provider_context_json"]["_tbt_provider_event_id"] = "wrong"
        with self.assertRaises(ValueError): decide(*args)


if __name__ == "__main__":
    unittest.main()
