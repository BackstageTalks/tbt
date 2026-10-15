import sys, unittest
from pathlib import Path
root = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(root if root.is_dir() else Path(__file__).resolve().parent))
from finalize_uploaded_research_crosswalk import unique_or_reject

def source(k,mid='e'):
    return {'source_key':k,'source_match_id':mid,'source_tour':'ATP'}
def cand(k,m):
    return {'source_key':k,'canonical_match_id':m,'new_null_keys':['p1_return_points_won'],
       'source_minus_index_seconds':3600,'source_minus_canonical_seconds':7200}
class TestSafety(unittest.TestCase):
    def test_valid_unlicensed_stays_research_only(self):
        v,d=unique_or_reject([cand('a','c')],[cand('a','c')],[source('a')]);self.assertEqual(len(v),1)
        self.assertFalse(v[0]['write_authorized']);self.assertFalse(v[0]['model_training_allowed'])
        self.assertFalse(v[0]['prematch_feature_allowed']);self.assertEqual(sum(d.values()),0)
    def test_duplicate_target_rejects_both(self):
        rows=[cand('a','c'),cand('b','c')]
        v,d=unique_or_reject(rows,rows,[source('a'),source('b')]);self.assertEqual(v,[])
        self.assertEqual(d['ambiguous_canonical_target'],2)
    def test_disagrees_with_baseline(self):
        v,d=unique_or_reject([cand('a','D')],[cand('a','C')],[source('a')]);self.assertEqual(v,[])
        self.assertEqual(d['not_unique_in_prior_attested_audit'],1)
    def test_duplicate_source_provenance(self):
        v,d=unique_or_reject([cand('a','c')],[cand('a','c')],[source('a'),source('a')]);self.assertEqual(v,[])
        self.assertEqual(d['duplicate_or_missing_source_provenance'],1)
    def test_no_missing(self):
        z=cand('a','c');z['new_null_keys']=[]
        v,d=unique_or_reject([z],[z],[source('a')]);self.assertEqual(v,[])
        self.assertEqual(d['no_missing_nulls'],1)
if __name__=='__main__':unittest.main()