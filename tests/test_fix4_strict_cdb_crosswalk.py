import unittest
from scripts.research.fix4_strict_cdb_crosswalk import tape,canonical_tape,canonical_ids,match_one
class TestFix4Strict(unittest.TestCase):
 def test_set_tape(self):
  self.assertEqual(tape('64 67(2) 64'),((6,4),(6,7),(6,4)))
  self.assertIsNone(tape('RET'))
  self.assertIsNone(tape('6 64'))
 def test_orientation(self):
  x={'p1_set1_games':4,'p2_set1_games':6,'p1_set2_games':6,'p2_set2_games':7}
  self.assertEqual(canonical_tape(x,False,2),((6,4),(7,6)))
  self.assertIsNone(canonical_tape({'p1_set1_games':6},True,2))
 def test_player_crosswalk_conflicts(self):
  rows=[{'tour':'atp','atp_tour_id':'AB12','canonical_player_id':'p1'},
        {'tour':'atp','atp_tour_id':'ab12','canonical_player_id':'p2'},
        {'tour':'atp','atp_tour_id':'cd34','canonical_player_id':'p3'}]
  good,bad=canonical_ids(rows);self.assertEqual(good,{'cd34':'p3'});self.assertEqual(bad,1)
 def test_unique_event_with_set_tape(self):
  import datetime as d
  source={'start':d.date(2015,1,1),'end':d.date(2015,1,10),'round':'f','tournament':'test open','winner_cdb_id':'p1','tape':((6,4),(7,6))}
  row={'scheduled_at':d.datetime(2015,1,5),'round_name':'Final','tournament':'Test Open','winner_id':'p1','status':'completed','player1_id':'p1','player2_id':'p2','match_id':'m1','stats_json':{'p1_set1_games':6,'p2_set1_games':4,'p1_set2_games':7,'p2_set2_games':6}}
  a,_,state=match_one(source,[row]);self.assertEqual(a[0]['match_id'],'m1');self.assertEqual(state,'unique_full_proof')
  _,_,state=match_one(source,[row,row]);self.assertEqual(state,'ambiguous_target')
  bad=dict(row);bad['stats_json']={};a,_,state=match_one(source,[bad]);self.assertIsNone(a)
if __name__=='__main__':unittest.main()