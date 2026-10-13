import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from audit_sackmann_2025_vs_cdb import score_sets,source_stats,full_score_equals,diff_fields,norm,nround

class ReadOnlySafetyTests(unittest.TestCase):
 def test_score(self):self.assertEqual(score_sets('6-4 5-7 7-6(4)'),[(6,4),(5,7),(7,6)])
 def test_reject_retirement(self):self.assertIsNone(score_sets('6-2 2-1 RET'))
 def test_reject_walkover(self):self.assertIsNone(score_sets('W/O'))
 def test_reject_unfinished(self):self.assertIsNone(score_sets('6-2'))
 def test_round_equivalence(self):self.assertEqual(nround('R32'),nround('Round of 32'))
 def test_norm_accents(self):self.assertEqual(norm('Jiri Lehecka'),norm('Jirí Lehecka'))
 def test_winner_p1_values(self):
  s={'w_ace':'12','l_ace':'2','w_df':'0','l_df':'5'}
  self.assertEqual(source_stats(s,True),{'p1_aces':12,'p2_aces':2,'p1_double_faults':0,'p2_double_faults':5})
 def test_winner_p2_values(self):
  s={'w_ace':'12','l_ace':'2','w_df':'0','l_df':'5'}
  self.assertEqual(source_stats(s,False),{'p2_aces':12,'p1_aces':2,'p2_double_faults':0,'p1_double_faults':5})
 def test_zero_is_not_null(self):
  s={'w_ace':'12','l_ace':'2','w_df':'0','l_df':'5'}
  n,e,c,k=diff_fields(s,{'p1_aces':None,'p2_aces':0,'p1_double_faults':0,'p2_double_faults':5},True)
  self.assertEqual((n,e,c,k),(1,2,1,4))
 def test_score_both_sides_exact(self):
  s={'score':'6-4 4-6 6-2'}
  d={'p1_set1_games':4,'p2_set1_games':6,'p1_set2_games':6,'p2_set2_games':4,'p1_set3_games':2,'p2_set3_games':6}
  self.assertTrue(full_score_equals(s,d,False))
  self.assertFalse(full_score_equals(s,dict(d,p2_set3_games=7),False))
 def test_score_requires_complete_cdb_tape(self):
  self.assertFalse(full_score_equals({'score':'6-4 6-3'},{'p1_set1_games':6,'p2_set1_games':4},True))
 def test_existing_additional_set_conflict(self):
  d={'p1_set1_games':6,'p2_set1_games':4,'p1_set2_games':6,'p2_set2_games':3,'p1_set3_games':1}
  self.assertFalse(full_score_equals({'score':'6-4 6-3'},d,True))
 def test_missing_source_not_imputed(self):
  d=source_stats({'w_ace':'','l_ace':'0','w_df':'','l_df':'2'},True)
  self.assertEqual(d,{'p2_aces':0,'p2_double_faults':2})

if __name__=='__main__':unittest.main()
