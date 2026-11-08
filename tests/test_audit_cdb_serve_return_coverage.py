import unittest
from scripts.audit_cdb_serve_return_coverage import profile,json_object

class Probe(unittest.TestCase):
    def test_no_missing_zero_confusion(self):
        rows=[{"match_id":"hist-js:atp:123",
               "stats_json":'{"p1_service_points_won":0.6,"p1_aces":0,"p2_return_points_won":0.4}',
               "provider_context_json":'{"_tbt_statistics":{"source":"jeff_sackmann_match_snapshot:abc.csv"}}'}]
        c,_=profile(rows)
        self.assertEqual(c["non_null_aces"],1)
        self.assertEqual(c.get("current_exact_complement_null_cells",0),0)
        self.assertEqual(c["native_null_aces"],1)
        self.assertEqual(c["exact_sackmann_lineage_markers"],1)
    def test_one_missing_complement(self):
        c,_=profile([{"match_id":"other","stats_json":'{"p1_service_points_won":0.7}',"provider_context_json":"{}"}])
        self.assertEqual(c["current_exact_complement_null_cells"],1)
    def test_inconsistent_complement(self):
        c,_=profile([{"match_id":"other","stats_json":'{"p1_service_points_won":0.7,"p2_return_points_won":0.4}',"provider_context_json":"{}"}])
        self.assertEqual(c["inconsistent_serve_return_pairs"],1)
    def test_pairwise_candidate_survives_unrelated_conflicting_pair(self):
        stats={"p1_service_points_won":0.7,
               "p2_first_serve_win":0.6,"p1_first_return_win":0.5}
        c,_=profile([{"match_id":"hist-js:atp:example",
                      "stats_json":__import__("json").dumps(stats),
                      "provider_context_json":"{}"}])
        self.assertEqual(c["potential_pairwise_complement_cells"],1)
        self.assertEqual(c["potential_complements_in_otherwise_conflicting_match"],1)
        self.assertEqual(c["candidate_p2_return_points_won"],1)

    def test_retrospective_tennisapi_conflict_marks_only_existing_evidence(self):
        import json
        rows = [
            {
                "match_id": "private-stable-id-1",
                "stats_json": json.dumps({"p1_aces": 7,
                                          "p2_break_point_serve_win": None}),
                "provider_context_json": json.dumps({"_tbt_statistics": {
                    "schema": 3, "source": "tennisapi1",
                    "status": "conflict",
                    "reason": "existing_canonical_stat_conflict",
                    "unsupported_keys": ["p1_aces", "p1_aces",
                                         "p2_break_point_return_win",
                                         "unexpected_arbitrary_key"],
                }}),
            },
            {
                "match_id": "private-stable-id-2",
                "stats_json": "{}",
                "provider_context_json": json.dumps({"_tbt_statistics": {
                    "source": "tennisapi1", "status": "conflict",
                    "reason": "provider_identity_mismatch",
                }}),
            },
        ]
        counts, samples = profile(rows)
        self.assertEqual(counts["tennisapi_conflict_rows"], 2)
        self.assertEqual(counts["tennisapi_conflict_reason_existing_canonical_stat_conflict"], 1)
        self.assertEqual(counts["tennisapi_conflict_reason_provider_identity_mismatch"], 1)
        self.assertEqual(counts["tennisapi_conflicting_field_p1_aces"], 1)
        self.assertEqual(counts["tennisapi_conflicting_field_p2_break_point_return_win"], 1)
        self.assertEqual(counts["tennisapi_conflicts_without_known_field_keys"], 1)
        self.assertEqual(counts["tennisapi_conflict_existing_bp_null_cells"], 8)
        self.assertEqual(counts["tennisapi_conflict_recovered_fields"], 0)
        self.assertNotIn("private-stable-id", json.dumps({"counts": counts, "samples": samples}))
        self.assertNotIn("unexpected_arbitrary_key", json.dumps(counts))

    def test_invalid_json(self):
        with self.assertRaises(ValueError):
            json_object('[]')

if __name__=="__main__":unittest.main()
