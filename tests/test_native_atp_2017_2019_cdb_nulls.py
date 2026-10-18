"""Synthetic safety checks for read-only native ATP CDB NULL-only census."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_native_atp_2017_2019_cdb_nulls as census


MID = "hist-js:atp:" + "a" * 24
SOURCE = {"w_bpFaced": "7", "w_bpSaved": "4", "l_bpFaced": "5", "l_bpSaved": "2"}
CONTEXT = {
    "_tbt_provider_event_id": MID,
    "_tbt_statistics": {
        "source": "jeff_sackmann_match_snapshot:atp_matches_2018.csv",
        "event_id": MID,
    },
}


def match(*, ctx=None, stats=None):
    return {
        "match_id": MID,
        "provider_context_json": json.dumps(CONTEXT if ctx is None else ctx),
        "stats_json": json.dumps({} if stats is None else stats),
    }


class NativeGapResearchSafety(unittest.TestCase):
    def test_valid_raw_breakpoint_counts_are_only_a_research_indicator(self):
        for p in (1, 2):
            self.assertEqual(census.native_bp_side(SOURCE, p), "valid_positive_denominator")
        result, _ = census.classify(SOURCE, match(), "2018")
        self.assertTrue(result["source_stat_lineage"])
        self.assertFalse(result["write_authorized"])
        self.assertTrue(all(x == "research_gap_requires_full_candidate_and_rights_review"
                            for x in result["field_states"].values()))

    def test_rank_only_identity_never_approves_stats_import(self):
        ctx = {"_tbt_provider_event_id": MID, "_tbt_rank_provenance": {"source": "rank.csv"}}
        result, _ = census.classify(SOURCE, match(ctx=ctx), "2018")
        self.assertFalse(result["source_stat_lineage"])
        self.assertFalse(result["write_authorized"])
        self.assertTrue(all(x == "missing_no_original_stat_lineage"
                            for x in result["field_states"].values()))

    def test_original_stats_source_must_match_year_and_event(self):
        self.assertTrue(census.source_stat_lineage(CONTEXT, MID, "2018"))
        self.assertFalse(census.source_stat_lineage(CONTEXT, MID, "2019"))
        self.assertFalse(census.source_stat_lineage(CONTEXT, "other", "2018"))

    def test_zero_and_invalid_denominators_are_held(self):
        zero = {**SOURCE, "l_bpFaced": "0", "l_bpSaved": "0"}
        status, _ = census.classify(zero, match(), "2018")
        self.assertEqual(status["field_states"]["p1_break_point_return_win"],
                         "missing_raw_bp_zero_denominator")
        self.assertEqual(status["field_states"]["p2_break_point_return_win"],
                         "research_gap_requires_full_candidate_and_rights_review")
        inconsistent = {**SOURCE, "w_bpFaced": "2", "w_bpSaved": "5"}
        self.assertEqual(census.native_bp_side(inconsistent, 2), "invalid_raw_count_constraints")

    def test_existing_canonical_field_is_never_a_missing_cell(self):
        state, _ = census.classify(
            SOURCE, match(stats={"p1_break_point_return_win": 0.6}), "2018"
        )
        self.assertEqual(state["field_states"]["p1_break_point_return_win"], "present")
        self.assertFalse(state["write_authorized"])

    def test_invalid_json_types_and_missing_source_counts_fail_closed(self):
        self.assertEqual(census.native_bp_side({}, 1), "missing_or_invalid_raw_counts")
        with self.assertRaises(ValueError):
            census.json_object("[]", "stats")
        with self.assertRaises(ValueError):
            census.json_object("{", "provider context")


    def test_strict_review_valid_match_and_correct_opposite_orientation(self):
        source = {
            "best_of": "3", "score": "6-4 6-4",
            "w_ace": "5", "w_df": "2", "w_svpt": "60",
            "w_1stIn": "40", "w_1stWon": "30", "w_2ndWon": "10",
            "w_SvGms": "10", "w_bpFaced": "6", "w_bpSaved": "4",
            "l_ace": "2", "l_df": "2", "l_svpt": "50",
            "l_1stIn": "30", "l_1stWon": "20", "l_2ndWon": "10",
            "l_SvGms": "10", "l_bpFaced": "8", "l_bpSaved": "5",
        }
        expected = "technically_consistent_rights_not_cleared"
        self.assertEqual(census.strict_count_candidate_review(source, {}), expected)
        self.assertEqual(census.strict_count_candidate_review(source, {
            "p1_return_break_points_converted_count": 3,
            "p2_return_break_points_converted_count": 2,
            "p1_break_point_return_win": 3 / 8,
            "p2_break_point_return_win": 2 / 6,
            "p2_break_point_serve_win": 5 / 8,
            "p1_break_point_serve_win": 4 / 6,
        }), expected)
        return source

    def test_strict_review_rejects_partial_or_retired_match(self):
        source = self.test_strict_review_valid_match_and_correct_opposite_orientation()
        self.assertEqual(census.strict_count_candidate_review(
            {**source, "score": "6-4 RET"}, {}), "incomplete_original_match")
        self.assertEqual(census.strict_count_candidate_review(
            {**source, "l_svpt": ""}, {}), "incomplete_original_match")
        self.assertEqual(census.strict_count_candidate_review(
            {**source, "l_bpSaved": "9"}, {}), "invalid_original_match_counts")

    def test_strict_review_rejects_existing_conflicts_and_bad_types(self):
        source = self.test_strict_review_valid_match_and_correct_opposite_orientation()
        for previous in (
            {"p1_return_break_points_converted_count": 2},
            {"p2_return_break_points_converted_count": 3},
            {"p1_break_point_return_win": 0.5},
            {"p2_break_point_serve_win": 0.5},
            {"p1_aces": 9},
            {"p2_double_faults": True},
            {"p1_service_points_won": "0.66"},
        ):
            self.assertEqual(census.strict_count_candidate_review(
                source, previous), "existing_cdb_stat_conflict")


if __name__ == "__main__":
    unittest.main()
