import json,unittest
from audit_cdb_wikidata_sofascore_identity_2025 import clean_wdqs,compare

def b(q,sofa,atp=None,wta=None):
 x={'person':{'value':'http://www.wikidata.org/entity/'+q},'sofa':{'value':str(sofa)}}
 if atp:x['atp']={'value':atp}
 if wta:x['wta']={'value':wta}
 return x

def p(q='Q11',atp=('A0E2',),wta=()):
 return {q:{'atp_ids':list(atp),'wta_ids':list(wta)}}

class SafeBridge(unittest.TestCase):
 def test_direct_id_code_match(self):
  wd=clean_wdqs({'results':{'bindings':[b('Q11','275923','A0E2')]}})
  x,c=compare({'atp':{'275923'},'wta':set()},p(),wd)
  self.assertEqual(len(x),1);self.assertEqual(x[0]['official_player_identifier'],'A0E2');self.assertFalse(x[0]['write_authorized'])
 def test_missing_provider_id(self):
  x,c=compare({'atp':{'777777'},'wta':set()},p(),clean_wdqs({'results':{'bindings':[b('Q11','275923','A0E2')]}}))
  self.assertEqual(x,[]);self.assertEqual(c['atp_not_in_Wikidata_P12302'],1)
 def test_same_digits_not_same_tour(self):
  wd=clean_wdqs({'results':{'bindings':[b('Q11','275923','A0E2')]}})
  x,c=compare({'atp':set(),'wta':{'275923'}},p(),wd)
  self.assertEqual(x,[])
 def test_collision_two_qids_fails_closed(self):
  wd=clean_wdqs({'results':{'bindings':[b('Q11','275923','A0E2'),b('Q12','275923','B0E2')]}})
  x,c=compare({'atp':{'275923'},'wta':set()},p(),wd)
  self.assertEqual(len(x),0);self.assertEqual(c['atp_ambiguous_P12302_QIDs'],1)
 def test_official_code_mismatch(self):
  wd=clean_wdqs({'results':{'bindings':[b('Q11','275923','A0E2')]}})
  x,c=compare({'atp':{'275923'},'wta':set()},p(atp=('A0F2',)),wd)
  self.assertEqual(len(x),0)
 def test_wta_p597(self):
  wd=clean_wdqs({'results':{'bindings':[b('Q12','123456',wta='326408')]}})
  x,c=compare({'atp':set(),'wta':{'123456'}},p('Q12',atp=(),wta=('326408',)),wd)
  self.assertEqual(len(x),1);self.assertEqual(x[0]['tour'],'wta')
 def test_bad_wdqs_rejected(self):
  with self.assertRaises(ValueError):clean_wdqs({})
 def test_bad_qid_rejected(self):
  with self.assertRaises(ValueError):clean_wdqs({'results':{'bindings':[b('bad','275923','A0E2')]}})
 def test_no_cdb_permissions_ever(self):
  wd=clean_wdqs({'results':{'bindings':[b('Q11','275923','A0E2')]}})
  x,_=compare({'atp':{'275923'},'wta':set()},p(),wd)
  self.assertFalse(x[0]['source_rights_cleared']);self.assertIsNone(x[0]['canonical_match_id'])
if __name__=='__main__':unittest.main()
