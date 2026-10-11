"""Synthetic fail-closed tests for Wimbledon 2023 72-cell retention verification."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import audit_wimbledon2023_retention72 as a

def observation(mid,field,value,state='READY_MISSING'):
    return {'canonical_match_id':mid,'field':field,'value':value,
        'source_id':a.SOURCE_FAMILY,'source_version':{'content_sha256':a.SOURCE_SHA},
        'provenance':{'raw_content_sha256':a.SOURCE_SHA},
        'scope':'whole_match','validation':{'state':state}}

def fixtures():
    mids=sorted(a.TARGET_IDS);first=[];advanced=[]
    for k,mid in enumerate(mids):
        for j,field in enumerate(sorted(a.FIRST)):
            first.append(observation(mid,field,k+j,'READY_MISSING' if k<3 else 'ALREADY_PRESENT'))
        for j,field in enumerate(sorted(a.EXTENDED)):
            advanced.append(observation(mid,field,k+j))
    return first,advanced

class WimbledonRetention(unittest.TestCase):
    def test_exact_fields(self):
        f,e=fixtures()
        expected=a.expected_values(f,e)
        rows={mid:{'stats_json':json.dumps({field:val for (m,field),val in expected.items() if m==mid})}
              for mid in a.TARGET_IDS}
        result=a.verify_retention_rows(rows,expected)
        self.assertEqual(result['verified_values'],72)
        self.assertEqual(result['verified_matches'],5)

    def test_missing_stage_rejected(self):
        f,e=fixtures()
        with self.assertRaisesRegex(ValueError,'COUNT_DRIFT'):
            a.expected_values(f,e[:-1])

    def test_untrusted_hash_rejected(self):
        f,e=fixtures()
        f[0]['source_version']['content_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'UNVERIFIED_SOURCE'):
            a.expected_values(f,e)

    def test_duplicated_cell_rejected(self):
        f,e=fixtures()
        e[1]=dict(e[0])
        with self.assertRaisesRegex(ValueError,'DUPLICATE_SOURCE'):
            a.expected_values(f,e)

    def test_missing_current_match_rejected(self):
        f,e=fixtures()
        with self.assertRaisesRegex(ValueError,'MISSING_RESTORED_MATCH'):
            a.verify_retention_rows({},a.expected_values(f,e))

    def test_changed_cell_rejected(self):
        f,e=fixtures();expected=a.expected_values(f,e)
        rows={mid:{'stats_json':json.dumps({field:val for (m,field),val in expected.items() if m==mid})}
              for mid in a.TARGET_IDS}
        mid,field=next(iter(expected))
        data=json.loads(rows[mid]['stats_json']);data[field]+=1
        rows[mid]['stats_json']=json.dumps(data)
        with self.assertRaisesRegex(ValueError,'CHANGED_2023_STAT_CELL'):
            a.verify_retention_rows(rows,expected)

    def test_bool_not_an_integer(self):
        f,e=fixtures();f[0]['value']=True
        with self.assertRaisesRegex(ValueError,'NON_INTEGER'):
            a.expected_values(f,e)

if __name__=='__main__':
    unittest.main()
