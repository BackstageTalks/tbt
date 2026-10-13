import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('audit',Path(__file__).resolve().parents[1]/'scripts/audit_pbp_source_vs_current_cdb.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class CandidateSafetyTests(unittest.TestCase):
    def test_numeric_ids_are_scoped_by_tour(self):
        row=dict(tourney_id='2025-1',tourney_date='20250101',match_num='1',
                 round='F',winner_id='281568',loser_id='999')
        self.assertNotEqual(audit.native_key('atp',row),audit.native_key('wta',row))
        for bad in (dict(row,loser_id='281568'),dict(row,winner_id=''),dict(row,match_num='')):
            with self.assertRaises(ValueError):audit.native_key('atp',bad)

    def test_generic_tournament_names_do_not_attest_event(self):
        self.assertFalse(audit.similar('ATP Open','WTA Open'))
        self.assertFalse(audit.similar('Open','Open'))
        self.assertTrue(audit.similar('Australian Open','Australian Open'))

    def test_only_json_null_and_absent_keys_are_gaps(self):
        for value in ('','null','nan','unknown',float('nan'),float('inf'),True,False,'3'):
            with self.subTest(value=value):
                self.assertEqual(audit.compare_cells({'p1_aces':value},{'p1_aces':3}),([],['p1_aces']))
        for existing in ({},{'p1_aces':None}):
            self.assertEqual(audit.compare_cells(existing,{'p1_aces':3}),(['p1_aces'],[]))

    def test_count_conflicts_are_not_rounded_away(self):
        self.assertEqual(audit.compare_cells({'p1_aces':3.001},{'p1_aces':3}),([],['p1_aces']))
        self.assertEqual(audit.compare_cells({'p1_aces':3},{'p1_aces':3}),([],[]))

if __name__=='__main__':unittest.main()
