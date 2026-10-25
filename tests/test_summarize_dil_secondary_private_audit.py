import unittest,sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent.parent/'scripts'))
from summarize_dil_secondary_private_audit import summarize
class AggregatePrivacyTests(unittest.TestCase):
 def test_strips_identifiers_and_unknown_fields(self):
  source={'schema':'DIL_SECONDARY_STRICT_CURRENT_CDB_PARITY_V1','status':'BLOCKED_CURRENT_CDB_PARITY',
    'secondary_promotion_allowed':False,'secret_player_name':'LEAK',
    'counts':{'cdb_matches':2,'a_hidden_identifier':'LEAK','dil_matches':1}}
  x=summarize(source)
  self.assertNotIn('LEAK',str(x));self.assertEqual(x['counts']['cdb_matches'],2)
 def test_rejects_wrong_schema(self):
  with self.assertRaises(ValueError):summarize({'schema':'other','counts':{}})
 def test_rejects_invalid_counts(self):
  with self.assertRaises(ValueError):summarize({'schema':'DIL_SECONDARY_STRICT_CURRENT_CDB_PARITY_V1','counts':{'cdb_matches':-1}})
if __name__=='__main__':unittest.main()
