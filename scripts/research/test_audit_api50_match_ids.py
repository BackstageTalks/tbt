import unittest
from audit_api50_match_ids import canonical_candidate,select_candidates,assess,parse_event

class Cases(unittest.TestCase):
 def fixture(self, tour='atp',n=1):
  return {'match_id':str(n),'tour':tour,'status':'finished','provider_context_json':{'_tbt_provider_event_id':str(n),'_tbt_event_identity':{'event_id':str(n),'home':str(n+100),'away':str(n+200),'status':'finished'}},'scheduled_at':__import__('datetime').datetime(2025,12,1,tzinfo=__import__('datetime').timezone.utc),'winner_id':str(n+100),'player1_id':str(n+100),'player2_id':str(n+200)}
 def event(self,n=1):
  return {'event':{'id':n,'homeTeam':{'id':n+100},'awayTeam':{'id':n+200},'startTimestamp':1764547200,'status':{'type':'finished'},'winnerCode':1}}
 def test_source(self):
  self.assertIsNotNone(canonical_candidate(self.fixture()))
 def test_malformed(self):
  r=self.fixture();r['provider_context_json']={'_tbt_provider_event_id':'2','_tbt_event_identity':{'event_id':'1','home':'101','away':'201'}};self.assertIsNone(canonical_candidate(r))
 def test_home_away_same(self):
  r=self.fixture();r['provider_context_json']['_tbt_event_identity']['away']='101';self.assertIsNone(canonical_candidate(r))
 def test_duplicated(self):
  r=self.fixture();self.assertRaises(ValueError,select_candidates,[r,r],1)
 def test_correct(self):
  self.assertEqual(assess(canonical_candidate(self.fixture()),self.event()),'SAME_PROVIDER_EVENT_PARTICIPANTS_TIME_WINNER_RECHECK_ONLY')
 def test_wrong_id(self):
  p=self.event();p['event']['id']=2;self.assertEqual(assess(canonical_candidate(self.fixture()),p),'DIFFERENT_EVENT_ID')
 def test_wrong_side(self):
  p=self.event();p['event']['homeTeam']['id']=201;self.assertEqual(assess(canonical_candidate(self.fixture()),p),'DIFFERENT_PARTICIPANT_IDS')
 def test_wrong_start(self):
  p=self.event();p['event']['startTimestamp']=123;self.assertEqual(assess(canonical_candidate(self.fixture()),p),'DIFFERENT_UTC_START')
 def test_wrong_winner(self):
  p=self.event();p['event']['winnerCode']=2;self.assertEqual(assess(canonical_candidate(self.fixture()),p),'DIFFERENT_WINNER_ID')
 def test_missing(self):
  self.assertEqual(assess(canonical_candidate(self.fixture()),{}),'INVALID_OR_EMPTY_API_EVENT')
 def test_not_finished(self):
  p=self.event();p['event']['status']['type']='inprogress';self.assertEqual(assess(canonical_candidate(self.fixture()),p),'API_NOT_FINISHED')
if __name__=='__main__':unittest.main()
