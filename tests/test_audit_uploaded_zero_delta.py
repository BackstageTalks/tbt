import unittest
from scripts.audit_actual_uploaded_source_field_delta import verify_stage_counts


class DeltaStageCountersTest(unittest.TestCase):
    def test_zero_candidates_when_counter_keys_are_omitted(self):
        verify_stage_counts([], {})
        verify_stage_counts([], {"all_score_values_already_present": 23})

    def test_positive_candidates(self):
        verify_stage_counts(
            [{"add_only_missing_score_fields": {"p1_set1_games":6,"p2_set1_games":4}}],
            {"stageable_score_matches_read_only":1,"stageable_score_missing_cells_read_only":2},
        )

    def test_nonempty_stage_not_allowed_by_zero_counter(self):
        with self.assertRaisesRegex(ValueError,"Stage row count"):
            verify_stage_counts([{"add_only_missing_score_fields":{"x":2}}],{})

    def test_wrong_cell_count_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"Stage cell count"):
            verify_stage_counts([{"add_only_missing_score_fields":{"x":2}}],
                {"stageable_score_matches_read_only":1,"stageable_score_missing_cells_read_only":2})

    def test_bad_counters(self):
        with self.assertRaises(ValueError):
            verify_stage_counts([], {"stageable_score_matches_read_only":-1})
        with self.assertRaises(ValueError):
            verify_stage_counts([], None)


if __name__ == "__main__":
    unittest.main()
