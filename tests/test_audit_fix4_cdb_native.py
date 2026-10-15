from __future__ import annotations
import unittest
from scripts.research.audit_fix4_cdb_native import native_key,official_keys_from_context

class NativeSourceKeyTests(unittest.TestCase):
    def test_original_id(self):
        self.assertEqual(native_key('atptour:2015:1536:MS001'),'2015/1536/ms001')
    def test_official_url_variants(self):
        self.assertEqual(native_key('https://www.atptour.com/en/scores/match-stats/archive/2015/1536/ms001'),'2015/1536/ms001')
        self.assertEqual(native_key('/en/scores/2015/1536/ms001/match-stats?isLive=False'),None)
    def test_forbid_imposter_host(self):
        self.assertIsNone(native_key('https://atptour.com.evil.com/en/scores/match-stats/archive/2015/1536/ms001'))
    def test_context_unambiguous(self):
        x={'_tbt':{'source_url':'https://atptour.com/en/scores/match-stats/archive/2015/1536/ms001'}}
        self.assertEqual(official_keys_from_context(x),{'2015/1536/ms001'})
    def test_context_ignore_arbitrary_text(self):
        self.assertFalse(official_keys_from_context({'random_note':'atptour:2015:1536:ms001'}))
    def test_noncontext_str(self):
        self.assertFalse(official_keys_from_context('not json'))

if __name__=='__main__':unittest.main()