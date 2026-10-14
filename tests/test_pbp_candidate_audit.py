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

    def test_bp_conversions_use_rate_keys_not_legacy_count_keys(self):
        for side in ('p1','p2'):
            values = audit.breakpoint_return_value(side, 7, 2)
            self.assertEqual(values, {side+'_break_point_return_win': 5/7})
            self.assertNotIn(side+'_break_points_won', values)
            self.assertEqual(audit.breakpoint_return_value(side, 0, 0),
                             {side+'_break_point_return_win': None})
        for bad in ((5, 6), (4, -1), (-1, 0)):
            with self.assertRaises(ValueError):
                audit.breakpoint_return_value('p1', *bad)

    def test_count_conflicts_are_not_rounded_away(self):
        self.assertEqual(audit.compare_cells({'p1_aces':3.001},{'p1_aces':3}),([],['p1_aces']))
        self.assertEqual(audit.compare_cells({'p1_aces':3},{'p1_aces':3}),([],[]))


    def test_alias_research_requires_opt_in(self):
        from collections import defaultdict
        exact=defaultdict(list)
        aliases=defaultdict(list,{('atp',(('djokovic','n'),('sinner','j'))):['research-candidate']})
        owners={('atp',('djokovic','n')):{'id-novak'},
                ('atp',('sinner','j')):{'id-jannik'}}
        self.assertEqual(audit.lookup_name_pair('atp','Novak Djokovic','Jannik Sinner',
            exact,aliases,owners), ((),None))
        self.assertEqual(audit.lookup_name_pair('atp','Novak Djokovic','Jannik Sinner',
            exact,aliases,owners,alias_research=True),(['research-candidate'],'alias_research_only'))

    def test_initial_surname_aliases_and_compound_names(self):
        self.assertEqual(audit.initial_surname_signature('Novak Djokovic'),('djokovic','n'))
        self.assertEqual(audit.initial_surname_signature('Djokovic N.'),('djokovic','n'))
        self.assertEqual(audit.initial_surname_signature('N. Djokovic'),('djokovic','n'))
        for name in ('Djokovic','J. M. del Potro','', 'N. N.'):
            with self.subTest(name=name):
                self.assertIsNone(audit.initial_surname_signature(name))
        self.assertIsNone(audit.alias_pair_signature('N. Djokovic','Novak Djokovic'))

    def test_ambiguous_aliases_are_rejected_even_with_matching_metadata(self):
        aliases={('atp',(('djokovic','n'),('sinner','j'))):['untrusted']}
        owners={('atp',('djokovic','n')):{'id-novak','id-nikolai'},
                ('atp',('sinner','j')):{'id-jannik'}}
        self.assertEqual(audit.lookup_name_pair('atp','Novak Djokovic','Jannik Sinner',
            {},aliases,owners,alias_research=True),((),None))
        self.assertFalse(audit.candidate_person_match('Novak Djokovic','Djokovic N.',
            'atp','id-novak',owners,alias_research=True))

    def test_alias_evidence_never_crosses_tours_or_ids(self):
        owners={('atp',('djokovic','n')):{'id1'},
                ('wta',('djokovic','n')):{'id2'}}
        self.assertTrue(audit.candidate_person_match('Novak Djokovic','Djokovic N.',
            'atp','id1',owners,alias_research=True))
        self.assertFalse(audit.candidate_person_match('Novak Djokovic','Djokovic N.',
            'atp','id2',owners,alias_research=True))
        self.assertFalse(audit.candidate_person_match('Novak Djokovic','Djokovic N.',
            'wta','id1',owners,alias_research=True))
        self.assertFalse(audit.candidate_person_match('Novak Djokovic','Djokovic N.',
            'atp','id1',owners))

    def test_exact_names_stay_exact_when_aliases_ambiguous(self):
        exact={('atp',('jannik sinner','novak djokovic')):['baseline']}
        aliases={}
        owners={('atp',('djokovic','n')):{'a','b'}}
        self.assertEqual(audit.lookup_name_pair('atp','Novak Djokovic','Jannik Sinner',
            exact,aliases,owners,alias_research=True),
            (['baseline'],'exact_normalized_name_pair'))

if __name__=='__main__':unittest.main()
