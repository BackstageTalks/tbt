import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.drive_source_cdb_gap import DEMOGRAPHIC, read_csv

class TestReadOnlyDriveGap(unittest.TestCase):
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
