import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from audit_cdb_provider_namespace_2025 import tally,object_only,FIELDS
class Safety(unittest.TestCase):
    def row(self,**kw):
        r={'match_id':'42','tour':'atp','provider_context_json':'{}','stats_json':'{}'};r.update(kw);return r
    def test_zero_not_null(self):
        a=tally([self.row(stats_json='{"p1_aces":0}')])['counts']
        self.assertEqual(a['non_null_p1_aces'],1);self.assertNotIn('null_p1_aces',a)
    def test_empty_string_is_not_null(self):
        a=tally([self.row(stats_json='{"p1_aces":""}')])['counts']
        self.assertEqual(a['non_null_p1_aces'],1)
    def test_null_is_null(self):
        a=tally([self.row(stats_json='{"p1_aces":null}')])['counts']
        self.assertEqual(a['null_p1_aces'],1)
    def test_missing_is_null(self):
        a=tally([self.row()])['counts'];self.assertEqual(a['null_p1_aces'],1)
    def test_duplicate_blocks(self):
        with self.assertRaises(ValueError):tally([self.row(),self.row()])
    def test_invalid_context_counted(self):
        a=tally([self.row(provider_context_json='{invalid')])['counts'];self.assertEqual(a['unparseable_provider_context'],1)
    def test_official_match_link_only(self):
        a=tally([self.row(provider_context_json='{"url":"https://www.atptour.com/en/scores/match-stats/archive/2025/339/MS015"}')])['counts'];self.assertEqual(a['has_explicit_official_atptour_match_link'],1)
    def test_no_false_official_link(self):
        a=tally([self.row(provider_context_json='{"url":"https://www.atptour.com/en/players/xyz"}')])['counts'];self.assertNotIn('has_explicit_official_atptour_match_link',a)
    def test_original_sides_count(self):
        a=tally([self.row(provider_context_json='{"_tbt_event_identity":{"event_id":"99","home":{"id":10},"away":{"id":20}}}')])['counts'];self.assertEqual(a['has_tbt_event_identity_both_participants'],1)
    def test_preapproval_prohibited(self):
        a=tally([self.row()]);self.assertEqual(a['new_cdb_fields_authorized'],0);self.assertEqual(a['cdb_writes'],0)
    def test_nonmatch_tour_excluded(self):
        a=tally([self.row(tour='doubles')])['counts'];self.assertEqual(a['non_atp_wta_rows'],1)
if __name__=='__main__':unittest.main()
