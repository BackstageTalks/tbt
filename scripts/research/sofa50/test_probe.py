import unittest
from probe import evaluate, pair
BASE={'event':'500','home':'10','away':'11','time':1700000000}
GOOD={'event':{'id':500,'homeTeam':{'id':10},'awayTeam':{'id':11},'startTimestamp':1700000000,'status':{'type':'finished'}}}
class Test(unittest.TestCase):
 def test_exact(self):self.assertEqual(evaluate(BASE,GOOD),'EXACT_EVENT_BOTH_PLAYERS_START_FINISHED')
 def test_event(self):self.assertEqual(evaluate(BASE,{'event':{**GOOD['event'],'id':999}}),'EVENT_ID_MISMATCH')
 def test_swapped(self):self.assertEqual(evaluate(BASE,{'event':{**GOOD['event'],'homeTeam':{'id':11},'awayTeam':{'id':10}}}),'PARTICIPANT_ID_MISMATCH')
 def test_time(self):self.assertEqual(evaluate(BASE,{'event':{**GOOD['event'],'startTimestamp':1700000001}}),'START_TIMESTAMP_MISMATCH')
 def test_missing(self):self.assertEqual(evaluate(BASE,{}),'NO_EVENT_OBJECT')
 def test_unfinished(self):self.assertEqual(evaluate(BASE,{'event':{**GOOD['event'],'status':{'type':'inprogress'}}}),'NOT_CONFIRMED_FINISHED')
 def test_missing_sides(self):self.assertIsNone(pair({'_tbt_event_identity':{'home':'10'}}))
 def test_self_match(self):self.assertIsNone(pair({'_tbt_event_identity':{'home':'10','away':'10'}}))
 def test_good_pair(self):self.assertEqual(pair({'_tbt_event_identity':{'home':10,'away':11}}),('10','11'))
if __name__=='__main__':unittest.main()
