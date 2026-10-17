import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from cdb_26_live_candidate_scan import player_match,tournament_match,round_code,score_compatible,candidates
S={'tour':'ATP','home_native_id':'723636','away_native_id':'433587','home_player':'Fritz T.','away_player':'Rublev A.','date_utc':'2021-03-17T17:15:00+00:00','tournament':'Dubai ATP','round':'1/8-finals','set_games_home_away':'3:6 1:6','source_winner_side':'2'}
C={'match_id':'canonical1','tour':'ATP','scheduled_at':'2021-03-17T17:00:00+00:00','player1_id':'firebaseA','player2_id':'firebaseB','player1_name':'Taylor Fritz','player2_name':'Andrey Rublev','tournament':'Dubai Open','round_name':'R16','score':'3-6 1-6','winner_id':'firebaseB'}
class CandidateGate(unittest.TestCase):
 def test_manyword_players(self):
  self.assertTrue(player_match('Van De Zandschulp B.','Botic Van De Zandschulp'))
  self.assertTrue(player_match('Ugo Carabelli C.','Camilo Ugo Carabelli'))
 def test_names_require_initial(self):self.assertFalse(player_match('Fritz T.','Jeremy Fritz'))
 def test_score(self):
  self.assertTrue(score_compatible('3:6 1:6','3-6 1-6',False))
  self.assertTrue(score_compatible('3:6 1:6','6-3 6-1',True))
  self.assertFalse(score_compatible('3:6 1:6','6-4 6-1',True))
 def test_round(self):
  self.assertEqual(round_code('1/8-finals'),round_code('R16'))
  self.assertNotEqual(round_code('Quarter-finals'),round_code('Semi-finals'))
 def test_tournament(self):
  self.assertTrue(tournament_match('French Open ATP','Roland Garros'))
  self.assertFalse(tournament_match('Dubai ATP','Miami ATP'))
 def test_unique_context_remains_unverified(self):
  r=candidates(S,[C])
  self.assertEqual(len(r),1)
  self.assertEqual(r[0]['canonical_match_id'],'canonical1')
  self.assertFalse(r[0]['source_native_ids_identical'])
 def test_wrong_score_or_year_not_promoted(self):
  self.assertEqual(candidates(S,[{**C,'score':'6-4 6-4'}]),[])
  self.assertEqual(candidates(S,[{**C,'scheduled_at':'2022-03-17T17:00:00+00:00'}]),[])
 def test_wrong_canonical_winner_rejected(self):
  self.assertEqual(candidates(S,[{**C,'winner_id':'firebaseA'}]),[])
 def test_swap_orientation(self):
  swapped={**C,'player1_name':'Andrey Rublev','player2_name':'Taylor Fritz','player1_id':'firebaseB','player2_id':'firebaseA','winner_id':'firebaseB','score':'6-3 6-1'}
  r=candidates(S,[swapped]);self.assertEqual(len(r),1)
  self.assertEqual(r[0]['orientation'],'reversed')
if __name__=='__main__':unittest.main()
