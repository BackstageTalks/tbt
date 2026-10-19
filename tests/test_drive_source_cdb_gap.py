import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.drive_source_cdb_gap import DEMOGRAPHIC, STAT_FIELDS, missing_stats, read_csv

class TestReadOnlyDriveGap(unittest.TestCase):
    def test_zero_is_not_missing_and_explicit_null_is_missing(self):
        missing=missing_stats('{"p1_aces":0,"p2_aces":null,"p1_service_points_won":0.0}')
        self.assertNotIn("p1_aces",missing)
        self.assertNotIn("p1_service_points_won",missing)
        self.assertIn("p2_aces",missing)
        self.assertEqual(len(missing),len(STAT_FIELDS)-2)

    def test_bad_canonical_stat_never_becomes_null(self):
        for raw in ('[]','{"p1_aces":NaN}','{"p1_aces":true}','{"p1_aces":"0"}'):
            with self.assertRaises(ValueError):missing_stats(raw)

    def test_absent_stats_object(self):
        self.assertEqual(missing_stats(None),list(STAT_FIELDS))

    def test_csv_coverage_and_duplicate_ids_are_not_import_claim(self):
        with TemporaryDirectory() as td:
            p=Path(td)/"atp_matches_2025.csv"
            headers=["match_id","winner_name","loser_name",*DEMOGRAPHIC]
            with p.open("w",newline="",encoding="utf8") as f:
                w=csv.DictWriter(f,fieldnames=headers);w.writeheader()
                w.writerow({"match_id":"one","winner_name":"A","loser_name":"B",
                            "winner_age":"25.5","loser_hand":"R"})
                w.writerow({"match_id":"one","winner_name":"A","loser_name":"B",
                            "winner_ht":"180"})
            report=read_csv(p)
            self.assertEqual(report["rows"],2)
            self.assertEqual(report["unique_source_match_ids"],1)
            self.assertEqual(report["duplicate_source_match_ids"],1)
            self.assertEqual(report["total_nonempty_demographic_cells"],3)

    def test_reject_missing_semantic_columns(self):
        with TemporaryDirectory() as td:
            p=Path(td)/"source.csv"
            p.write_text("match_id,winner_name\n1,A\n",encoding="utf8")
            with self.assertRaisesRegex(ValueError,"mandatory"):
                read_csv(p)

if __name__ == "__main__":unittest.main()

