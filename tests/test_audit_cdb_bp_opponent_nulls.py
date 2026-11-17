"""Exact opponent BP complement audit must fail closed."""
import unittest
from scripts.audit_cdb_bp_opponent_nulls import classify, add_record
from collections import Counter


class TestBPComplementAudit(unittest.TestCase):
    def test_save_to_opponent_convert_and_reverse(self):
        label, values, _ = classify({"p1_break_point_serve_win": .8,
                                      "p2_break_point_serve_win": .6})
        self.assertEqual(label, "interior_null_complement_candidate")
        self.assertAlmostEqual(values["p2_break_point_return_win"], .2)
        self.assertAlmostEqual(values["p1_break_point_return_win"], .4)
        self.assertEqual(len(values), 2)

    def test_convert_to_opponent_save(self):
        _, values, _ = classify({"p1_break_point_return_win": .4})
        self.assertAlmostEqual(values["p2_break_point_serve_win"], .6)

    def test_conflict_in_other_pair_vetoes_entire_match(self):
        code, values, _ = classify({"p1_break_point_serve_win": .7,
                                    "p2_break_point_serve_win": .6,
                                    "p1_break_point_return_win": .5})
        self.assertEqual(code, "contradictory_bp_pair")
        self.assertFalse(values)

    def test_no_observed_or_zero_opportunity_boundary(self):
        self.assertFalse(classify({})[1])
        self.assertEqual(classify({"p1_break_point_serve_win": 0})[0],
                         "boundary_requires_denominator_witness")
        self.assertEqual(classify({"p1_break_point_serve_win": 1})[0],
                         "boundary_requires_denominator_witness")

    def test_invalid_numbers_quarantined(self):
        for invalid in (float("nan"), float("inf"), -0.3, 2.0, True, "0.5"):
            with self.subTest(invalid=repr(invalid)):
                self.assertEqual(classify({"p1_break_point_serve_win": invalid})[0],
                                 "invalid_bp_rate")

    def test_completed_only_and_json(self):
        c = Counter()
        add_record(c, "scheduled", '{"p1_break_point_serve_win":0.6}')
        self.assertEqual(c["possible_new_null_bp_values"], 0)
        add_record(c, "completed", '{"p1_break_point_serve_win":0.6}')
        self.assertEqual(c["possible_new_null_bp_values"], 1)
        self.assertEqual(c["candidate_p2_break_point_return_win"], 1)


if __name__ == "__main__":
    unittest.main()
