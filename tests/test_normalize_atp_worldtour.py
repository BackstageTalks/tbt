"""Regression tests for pinned ATP World Tour source-only adapter."""
import csv
import os
import tempfile
import unittest
from pathlib import Path

from scripts.normalize_atp_worldtour import completed, valid, STATS, convert

EXPECTED_DIGEST = 'd7ea6898fcdb42e58f3342fd3deac506ba4f2872493d76cde4db77a3d8463bc4'


class WorldTourAdapterTests(unittest.TestCase):
    def test_completed_score_fail_closed(self):
        for score, w, l in [('64 76(5)', '2','0'), ('36 75 63','2','1'), ('63 46 63 57 62','3','2')]:
            self.assertTrue(completed(score,w,l))
        for score,w,l in [('64 64','2','1'),('64 RET','2','0'),('66 64','2','0'),('64 64','3','0')]:
            self.assertFalse(completed(score,w,l))

    def test_stats_invariants(self):
        root = os.environ.get('BLINQ_PINNED_ATP_DIR')
        if not root:
            self.skipTest('Full pinned source not available in unit environment')
        path = Path(root)/'csv/3_match_stats/match_stats_2020.csv'
        with path.open(newline='') as f:
            first = dict(zip(STATS, next(csv.reader(f))))
        self.assertTrue(valid(first))
        for field in ('winner_break_points_saved','winner_return_points_won','loser_aces'):
            corrupt=dict(first);corrupt[field]=str(int(first[field])+1000)
            self.assertFalse(valid(corrupt),field)
        for field in ('winner_aces','loser_service_points_total'):
            corrupt=dict(first);corrupt[field]='NaN'
            self.assertFalse(valid(corrupt),field)

    def test_full_source_deterministic_immutable_golden(self):
        root=os.environ.get('BLINQ_PINNED_ATP_DIR')
        if not root:
            self.skipTest('Pinned source not available in unit environment')
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            report=convert(Path(root),base/'normalized.csv',base/'report.json')
            self.assertEqual(report['output_rows'],24207)
            self.assertEqual(report['output_csv_sha256'],EXPECTED_DIGEST)
            self.assertEqual(report['cdb_writes'],0)
            self.assertEqual(report['api_requests'],0)
            with (base/'normalized.csv').open(newline='') as f:
                row=next(csv.DictReader(f))
                self.assertEqual(row['source_date_kind'],'tournament_start')
                self.assertTrue(row['source_record_id'])


if __name__ == '__main__':
    unittest.main()
