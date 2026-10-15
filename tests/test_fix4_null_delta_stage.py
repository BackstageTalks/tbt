import unittest
from scripts.research.fix4_null_delta_stage import side,incoming_stats,candidate_delta
class NullOnlyTests(unittest.TestCase):
 def test_rate_and_zero(self):
  d=['']*59
  d[7]='0';d[8]='2';d[11]='10';d[12]='20';d[13]='0';d[14]='0';d[26]='30';d[27]='40';d[28]='15';d[29]='35'
  r=side(d)
  self.assertEqual(r['aces'],0);self.assertEqual(r['first_serve_win'],0.5)
  self.assertNotIn('second_serve_win',r)
 def test_orient(self):
  d=['']*59;d[0]='test';d[7]='5';d[34]='1'
  x=incoming_stats(d,False)
  self.assertEqual(x['p2_aces'],5);self.assertEqual(x['p1_aces'],1)
 def test_null_only_no_overwrite(self):
  add,conf,match=candidate_delta({'p1_aces':4.,'p1_first_serve_win':0.5,'p2_aces':2.},{'p1_aces':4.,'p1_first_serve_win':None})
  self.assertEqual(add,{'p1_first_serve_win':0.5,'p2_aces':2.});self.assertEqual(conf,[])
 def test_conflict_reject(self):
  add,conf,match=candidate_delta({'p1_aces':8.},{'p1_aces':4.})
  self.assertEqual(conf,['p1_aces'])
if __name__=='__main__':unittest.main()