import unittest
from scripts.audit_cdb_serve_return_coverage import profile,json_object

class Probe(unittest.TestCase):
    def test_no_missing_zero_confusion(self):
        rows=[{"match_id":"hist-js:atp:123",
               "stats_json":'{"p1_service_points_won":0.6,"p1_aces":0,"p2_return_points_won":0.4}',
               "provider_context_json":'{"_tbt_statistics":{"source":"jeff_sackmann_match_snapshot:abc.csv"}}'}]
        c,_=profile(rows)
        self.assertEqual(c["non_null_aces"],1)
        self.assertEqual(c["current_exact_complement_null_cells"],0)
        self.assertEqual(c["native_null_aces"],1)
        self.assertEqual(c["exact_sackmann_lineage_markers"],1)
    def test_one_missing_complement(self):
        c,_=profile([{"match_id":"other","stats_json":'{"p1_service_points_won":0.7}',"provider_context_json":"{}"}])
        self.assertEqual(c["current_exact_complement_null_cells"],1)
    def test_inconsistent_complement(self):
        c,_=profile([{"match_id":"other","stats_json":'{"p1_service_points_won":0.7,"p2_return_points_won":0.4}',"provider_context_json":"{}"}])
        self.assertEqual(c["inconsistent_serve_return_pairs"],1)
    def test_invalid_json(self):
        with self.assertRaises(ValueError):
            json_object('[]')

if __name__=="__main__":unittest.main()
