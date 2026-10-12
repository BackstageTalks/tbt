import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from review_tml_cc0_current_cdb_events import (
    valid_candidate_edges, score_event_candidates, compare_core_service_cells, sha_file,
)


def proposed(code="AB12", canonical="CAN1", qid="Q123"):
    return {"source_atp_player_id": code,
            "candidate_canonical_player_id": canonical,
            "wikidata_qid": qid,
            "status": "REVIEW_ONLY_EVENT_AND_BOTH_SIDES_NOT_YET_ATTESTED",
            "canonical_match_id": None, "import_ready": False,
            "write_authorized": False}


def cc0(code="AB12", canonical="CAN1", qid="Q123", name="A Player"):
    return {"tour": "atp", "source": "Wikidata", "license": "CC0-1.0",
            "evidence": "unique_exact_name_both_sides_plus_tour_specific_id",
            "wikidata_qid": qid, "player_id": canonical,
            "canonical_name": name, "external_ids": {"atp": [code]}}


def old_link():
    return {"tour": "atp", "source": "BlinQ verified CDB plus Wikidata CC0",
            "evidence": "official_atp_identifier_unique_registry_full_name_and_nonconflicting_cdb",
            "wikidata_qid": "Q456", "atp_tour_id": "CD34",
            "canonical_player_id": "CAN2", "canonical_name": "B Player"}


def match(**updates):
    data = {"match_id": "M1", "tour": "atp",
            "scheduled_day": "2024-01-05",
            "player1_id": "CAN1", "player2_id": "CAN2",
            "player1_name": "A Player", "player2_name": "B Player",
            "winner_id": "CAN1", "tournament": "Test Open",
            "round_name": "QF", "surface": "Hard",
            "best_of": 3, "status": "finished", "stats_json": "{}"}
    data.update(updates)
    return data


def source(**updates):
    data = {"schema": 1, "tour": "atp",
            "canonical_match_id": None, "write_authorized": False,
            "import_ready": False,
            "linkage_status": "SOURCE_UNLINKED_ORIGINAL_IDS_PRESENT",
            "source_namespace": "tml-atp-2024",
            "source_native_event_key": ["tournament-match", "2024-123", "7"],
            "source_winner_id": "AB12", "source_loser_id": "CD34",
            "source_date": "20240101", "source_round": "QF",
            "raw_columns": {"tourney_name": "Test Open",
                            "surface": "Hard", "best_of": "3"}}
    data.update(updates)
    return data


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.canon = [match()]
        self.legacy = [old_link()]
        self.new = [proposed()]
        self.cc0 = [cc0()]

    def bridges(self, **updates):
        a, c, l, m = self.new, self.cc0, self.legacy, self.canon
        return valid_candidate_edges(a, l, c, m)

    def test_exact_official_id_qid_and_fresh_cdb_names_are_candidates_only(self):
        links, counts = self.bridges()
        self.assertEqual(links["AB12"], "CAN1")
        self.assertEqual(links["CD34"], "CAN2")
        self.assertEqual(counts["fresh_player_id_bridge_review_candidates"], 1)
        possible, stats = score_event_candidates([source()], self.canon, links)
        self.assertEqual(len(possible), 1)
        self.assertEqual(stats["unique_full_metadata_candidates_review_only"], 1)
        self.assertIs(possible[0]["import_ready"], False)
        self.assertIs(possible[0]["write_authorized"], False)
        self.assertIs(possible[0]["independent_event_id_attested"], False)
        self.assertIs(possible[0]["score_attested"], False)

    def test_changed_canonical_name_disables_new_player_bridge(self):
        self.canon = [match(player1_name="Different Player")]
        links, counts = self.bridges()
        self.assertNotIn("AB12", links)
        self.assertEqual(counts["blocked_stale_or_ambiguous_current_cdb_name"], 1)

    def test_wrong_official_atp_id_is_not_name_linked(self):
        self.cc0 = [cc0(code="EF67")]
        links, counts = self.bridges()
        self.assertNotIn("AB12", links)
        self.assertEqual(counts["blocked_ambiguous_cc0"], 1)

    def test_two_wikidata_qids_for_same_atp_code_quarantined(self):
        self.cc0.append(cc0(qid="Q999", canonical="CAN2"))
        links, counts = self.bridges()
        self.assertNotIn("AB12", links)
        self.assertEqual(counts["blocked_ambiguous_cc0"], 1)

    def test_duplicate_proposal_id_is_hard_error(self):
        self.new.append(proposed("ab12"))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.bridges()

    def test_preauthorized_proposal_is_hard_error(self):
        self.new[0]["write_authorized"] = True
        with self.assertRaisesRegex(ValueError, "preapproved"):
            self.bridges()

    def test_winner_mismatch_fails_event_gate(self):
        links, _ = self.bridges()
        matches = [match(winner_id="CAN2")]
        possible, stats = score_event_candidates([source()], matches, links)
        self.assertEqual(possible, [])
        self.assertEqual(stats["no_full_metadata_match"], 1)

    def test_tournament_round_surface_or_bestof_mismatch_fails(self):
        links, _ = self.bridges()
        for bad in (match(tournament="Other Event"),
                    match(round_name="SF"), match(surface="Clay"),
                    match(best_of=5)):
            with self.subTest(canonical=bad):
                possibles, _ = score_event_candidates([source()], [bad], links)
                self.assertEqual(possibles, [])

    def test_date_before_week_or_too_late_fails(self):
        links, _ = self.bridges()
        for day in ("2023-12-31", "2024-02-02"):
            possibles, _ = score_event_candidates(
                [source()], [match(scheduled_day=day)], links)
            self.assertEqual(possibles, [])

    def test_multiple_identical_canonical_candidates_quarantined(self):
        links, _ = self.bridges()
        possibles, counts = score_event_candidates(
            [source()], [match(), match(match_id="M2")], links)
        self.assertEqual(possibles, [])
        self.assertEqual(counts["ambiguous_canonical_event_candidates"], 1)

    def test_reused_original_source_event_key_errors_not_first_wins(self):
        links, _ = self.bridges()
        with self.assertRaisesRegex(ValueError, "Duplicate original"):
            score_event_candidates([source(), source()], self.canon, links)

    def test_bad_source_import_approval_causes_hard_error(self):
        links, _ = self.bridges()
        with self.assertRaisesRegex(ValueError, "preauthorized"):
            score_event_candidates([source(import_ready=True)], self.canon, links)

    def test_both_player_ids_required(self):
        links, _ = self.bridges()
        possibles, counts = score_event_candidates(
            [source(source_loser_id="UNKNOWN")], self.canon, links)
        self.assertEqual(possibles, [])
        self.assertEqual(counts["blocked_unverified_current_player_pair"], 1)

    def test_null_equal_and_conflicting_source_service_values_stay_review_only(self):
        fields = {"w_ace": "5", "w_df": "2", "l_ace": "1", "l_df": "0"}
        current = match(stats_json=json.dumps({
            "p1_aces": 5, "p1_double_faults": 999,
            "p2_aces": None, "p2_double_faults": 0}))
        stats = compare_core_service_cells(fields, current, "CAN1", "CAN2")
        self.assertEqual(stats["observed_source_core_stat_cells"], 4)
        self.assertEqual(stats["existing_core_stat_cells_equal"], 2)
        self.assertEqual(stats["conflicting_core_stat_cells"], 1)
        self.assertEqual(stats["current_null_core_cells_review_only"], 1)
        links, _ = self.bridges()
        observed, counts = score_event_candidates(
            [source(raw_columns={**source()["raw_columns"], **fields})], [current], links)
        self.assertEqual(len(observed), 1)
        self.assertFalse(observed[0]["import_ready"])
        self.assertFalse(observed[0]["write_authorized"])
        self.assertIsNone(observed[0]["candidate_new_null_fields"])
        self.assertEqual(counts["current_null_core_cells_review_only"], 1)

    def test_swapped_original_winner_orientation_maps_to_p2_fields(self):
        stats = compare_core_service_cells(
            {"w_ace": "3", "w_df": "1", "l_ace": "8", "l_df": "4"},
            match(stats_json=json.dumps({"p1_aces": 8, "p2_aces": 3})),
            "CAN2", "CAN1")
        self.assertEqual(stats["existing_core_stat_cells_equal"], 2)
        self.assertEqual(stats["current_null_core_cells_review_only"], 2)

    def test_unknown_or_non_numeric_source_stats_never_count_as_null(self):
        result = compare_core_service_cells(
            {"w_ace": "", "w_df": "-1", "l_ace": "NaN", "l_df": "2"},
            match(), "CAN1", "CAN2")
        self.assertEqual(result["unusable_source_core_stat_cells"], 3)
        self.assertEqual(result["current_null_core_cells_review_only"], 1)

    def test_source_sha_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "source.txt"
            path.write_text(json.dumps({"source": "safe"}))
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(sha_file(path, sha), sha)
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                sha_file(path, "b"*64)


if __name__ == "__main__":
    unittest.main()
