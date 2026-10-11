"""Isolated standard-library tests for read-only WTA 2026 source auditing."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import audit_wta2026_excel_readonly as a

def record(**kw):
    r=dict(match_id="m1",tour="wta",scheduled_at="2026-01-04T12:00:00Z",
       player1_name="Sara Bejlek",player2_name="Panna Udvardy",player1_id="p1",
       player2_id="p2",winner_id="p1",surface="Hard",tournament="ASB Classic",
       round_name="1st Round",player1_rank=None,player2_rank=87)
    r.update(kw);return r

def source(**kw):
    r=dict(Winner="Bejlek S.",Loser="Udvardy P.",Comment="Completed",
        _day="2026-01-04",Surface="Hard",Tournament="ASB Classic",
        Round="1st Round",WRank=93,LRank=87)
    r.update(kw);return r

class WTAReadOnlyContract(unittest.TestCase):
    def test_weak_name_match_never_approved(self):
        r=a.compare([source()],[record()])
        self.assertEqual(r["unique_name_day_surface_winner_DIAGNOSTIC_ONLY"],1)
        self.assertEqual(r["RESEARCH_rank_null_NOT_WRITEABLE"],1)
        self.assertEqual(r["rank_equal"],1)
        self.assertEqual(r["approved_added_values"],0)
        self.assertEqual(r["independently_attested_source_player_event_ID"],0)

    def test_ambiguous_identity_quarantined(self):
        r=a.compare([source()],[record(),record(match_id="m2")])
        self.assertEqual(r["ambiguous_name_day"],1)
        self.assertEqual(r["approved_added_values"],0)

    def test_winner_conflict_quarantined(self):
        self.assertEqual(a.compare([source()],[record(winner_id="p2")])["winner_conflict"],1)

    def test_surface_conflict_quarantined(self):
        self.assertEqual(a.compare([source()],[record(surface="Clay")])["surface_mismatch"],1)

    def test_walkovers_excluded(self):
        self.assertEqual(a.compare([source(Comment="Walkover")],[record()])["rejected_noncompleted"],1)

    def test_forged_workbook_sha_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"fake.xlsx";p.write_bytes(b"forged")
            with self.assertRaisesRegex(ValueError,"SOURCE_SHA256_DRIFT"):a.workbook_rows(p)

    def test_duplicate_canonical_ids_rejected(self):
        with self.assertRaisesRegex(ValueError,"Duplicate or absent"):a.compare([source()],[record(),record()])

if __name__=="__main__":unittest.main()
