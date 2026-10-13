import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from audit_exact_2025_id_namespace import analyze,parts,event,jsonobj,stamp

def cdb(i='123456',home='1001',away='2002',scheduled='2025-04-01T08:00:00+00:00',winner='1001',stats=None):
 import json
 return {'match_id':'abc','tour':'atp','scheduled_at':scheduled,'status':'finished','winner_id':winner,
         'provider_context_json':json.dumps({'_tbt_provider_event_id':i,'_tbt_event_identity':{'event_id':i,'home':home,'away':away}}),
         'stats_json':json.dumps(stats if stats is not None else {'p1_aces':None,'p2_aces':0,'p1_double_faults':None,'p2_double_faults':None})}
def src(i='123456',home='1001',away='2002',ts='1743494400',winner_code='1'):
 return {'tour':'atp','event_id':i,'home_id':home,'away_id':away,'ts':ts,'status':'FINISHED','winner_code':winner_code}
class Guard(unittest.TestCase):
 def test_no_event_id_match(self):
  r=analyze([src(i='1')],[cdb()]);self.assertEqual(r['counts'].get('unique_event_id_equal',0),0)
 def test_event_id_match_is_not_canonical_proof(self):
  r=analyze([src()],[cdb()]);self.assertEqual(r['approved_CDB_NULL_fields'],0);self.assertEqual(r['CDB_writes'],0)
 def test_wrong_player_ids_rejected(self):
  r=analyze([src(home='2020')],[cdb()]);self.assertEqual(r['counts'].get('same_event_number_but_different_players'),1)
 def test_cross_tour_id_collision_is_not_match(self):
  s=src();s['tour']='wta';r=analyze([s],[cdb()]);self.assertEqual(r['counts'].get('unique_event_id_equal',0),0)
 def test_wrong_date(self):
  r=analyze([src()],[cdb(scheduled='2025-04-02T08:00:00+00:00')]);self.assertEqual(r['counts'].get('same_event_players_exact_time',0),0)
 def test_correct_event_pair_exact_date_without_rights_is_blocked(self):
  r=analyze([src()],[cdb()]);self.assertEqual(r['counts'].get('all_numeric_event_players_time_winner_match_RESEARCH_ONLY'),1);self.assertEqual(r['approved_CDB_NULL_fields'],0)
 def test_existing_zero_not_null(self):
  r=analyze([src()],[cdb()]);self.assertEqual(r['counts'].get('candidate_CDB_NULL_fields_NOT_AUTHORIZED'),3)
 def test_duplicate_source_event_fails(self):
  with self.assertRaises(ValueError):analyze([src(),src()],[cdb()])
 def test_duplicate_provider_event_fails_closed(self):
  r=analyze([src()],[cdb(),cdb()]);self.assertEqual(r['counts'].get('duplicate_CDB_provider_ID'),1);self.assertEqual(r['counts'].get('all_numeric_event_players_time_winner_match_RESEARCH_ONLY',0),0)
 def test_invalid_provider_context_fails_closed(self):
  self.assertIsNone(event(jsonobj('not-json')))
 def test_mismatched_internal_context_event_fails_closed(self):
  self.assertIsNone(parts({'_tbt_event_identity':{'event_id':'987','home':'1001','away':'2002'}},'123'))
 def test_winner_mismatch_does_not_count(self):
  r=analyze([src()],[cdb(winner='2002')]);self.assertEqual(r['counts'].get('all_numeric_event_players_time_winner_match_RESEARCH_ONLY',0),0)
if __name__=='__main__':unittest.main()
