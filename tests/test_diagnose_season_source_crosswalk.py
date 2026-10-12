import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from diagnose_season_source_crosswalk import sides,pair,date_utc,compare
from collections import Counter,defaultdict

class IdentityTests(unittest.TestCase):
    def test_source_pair_is_order_independent(self):
        self.assertEqual(pair("9","42"),("42","9"))
    def test_source_pair_malformed_fails(self):
        self.assertIsNone(pair("42","42"))
        self.assertIsNone(pair("","42"))
    def test_provider_context_both_sides(self):
        ctx={"_tbt_event_identity":{"event_id":"10","home":"42","away":"9"},
             "homeTeam":{"id":42},"awayTeam":{"id":9}}
        self.assertEqual(sides(ctx),("42","9"))
    def test_context_alias_conflict_quarantines(self):
        ctx={"_tbt_event_identity":{"home":"42","away":"9"},
             "homeTeam":{"id":"5"},"awayTeam":{"id":"9"}}
        self.assertIsNone(sides(ctx))
    def test_no_names_as_ids(self):
        self.assertIsNone(sides({"homeTeam":{"name":"A"},"awayTeam":{"name":"B"}}))
    def test_date_utc_is_exact(self):
        self.assertEqual(date_utc(1640995200),"2022-01-01")
    def test_different_provider_ids_cannot_be_p1_p2_by_assumption(self):
        rec={"raw":{"home_id":"42","away_id":"9","winner_code":"1"},
             "ts":1640995200}
        ctx={"provider_event_id":"other-event","_tbt_event_identity":{"event_id":"other-event","home":"42","away":"9"}}
        can={"player1_id":"different-p1","player2_id":"different-p2","winner_id":"different-p1","status":"finished"}
        by=defaultdict(list,{("atp",("42","9")):[(1640995200,can,ctx,("42","9"))]})
        counts=Counter()
        compare({("atp","source-event"):rec},by,defaultdict(list),defaultdict(list),counts)
        self.assertEqual(counts["provider_pair_no_verified_canonical_player_mapping"],1)
        self.assertEqual(counts["provider_pair_strict_all_but_event_namespace"],0)

if __name__=="__main__":unittest.main()
