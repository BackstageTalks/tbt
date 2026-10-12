import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "scripts"))
import blinq_season_cdb_gate as m

ST=1640991900
MID='aabbccddee00112233445566'
RAW={'home_id':'42','away_id':'99','winner_code':'1'}
SRC={'raw':RAW,'source_sha':'a'*64,'ts':ST,
     'vals':{'home_aces':3,'away_aces':2,'home_double_faults':4,'away_double_faults':1},
     'src':'2022-atp-season.csv'}
CTX={'_tbt_event_identity':{'event_id':'123','home':'42','away':'99'},'provider_event_id':'123'}
CAN={'match_id':MID,'tour':'atp','scheduled_at':datetime.fromtimestamp(ST,timezone.utc),
     'player1_id':'42','player2_id':'99','winner_id':'42','status':'finished','stats_json':'{}',
     'provider_context_json':json.dumps(CTX)}

class GateTest(unittest.TestCase):
    def audit(self,old='{}',canon=None,ctx=None):
        c=dict(CAN,stats_json=old) if canon is None else canon
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(m,'source_rows',return_value=({('atp','123'):SRC},m.Counter(source_rows=1))):
                with patch.object(m,'read_canonical_files',return_value=({('atp','123'):[(c,CTX if ctx is None else ctx)]},m.Counter(current_cdb_rows_examined=1))):
                    report=m.analyze(folder,folder,{f'history-{y}.parquet':'0'*64 for y in m.REQUIRED_YEARS},folder)
                    f=(Path(folder)/'candidate-matches-private.jsonl').read_text().strip()
                    return report,json.loads(f) if f else None

    def test_null_fields_are_research_only(self):
        r,c=self.audit()
        self.assertEqual(r['counts']['research_only_null_ace_df_cells'],4)
        self.assertFalse(r['write_authorized'])
        self.assertEqual(c['observations'],{'p1_aces':3,'p2_aces':2,'p1_double_faults':4,'p2_double_faults':1})

    def test_existing_four_fields_already_equal(self):
        r,c=self.audit('{"p1_aces":3,"p2_aces":2,"p1_double_faults":4,"p2_double_faults":1}')
        self.assertIsNone(c);self.assertEqual(r['counts']['already_equal_ace_df_cells'],4)

    def test_existing_zero_is_not_missing(self):
        r,c=self.audit('{"p1_aces":0}')
        self.assertIsNone(c);self.assertEqual(r['counts']['conflicting_ace_df_matches'],1)

    def test_reverse_player_order(self):
        r,c=self.audit(canon=dict(CAN,player1_id='99',player2_id='42'))
        self.assertEqual(c['observations']['p1_aces'],2)
        self.assertEqual(c['observations']['p2_aces'],3)

    def test_winner_mismatch_blocks(self):
        r,c=self.audit(canon=dict(CAN,winner_id='99'))
        self.assertIsNone(c);self.assertEqual(r['counts']['canonical_winner_conflicts'],1)

    def test_unmatched_player_witness_blocks(self):
        ctx={'_tbt_event_identity':{'event_id':'123','home':'700','away':'99'},'provider_event_id':'123'}
        r,c=self.audit(ctx=ctx)
        self.assertIsNone(c);self.assertEqual(r['counts']['missing_or_wrong_independent_home_away_ids'],1)

    def test_exact_start_required(self):
        r,c=self.audit(canon=dict(CAN,scheduled_at=datetime.fromtimestamp(ST+60,timezone.utc)))
        self.assertIsNone(c);self.assertEqual(r['counts']['different_utc_start'],1)

    def test_no_name_only_or_utc_naive(self):
        self.assertIsNone(m.source_player_sides({'_tbt_event_identity':{'event_id':'123','home':{'name':'A'},'away':{'name':'B'}}},'123'))
        self.assertIsNone(m.utc_start('2022-01-01T00:00:00'))

    def test_inconsistent_provider_marker_blocks(self):
        self.assertIsNone(m.provider_event_id({'event_id':123,'_tbt_provider_event_id':999}))

    def test_negative_non_integer_or_impossible_count_blocks(self):
        for bad in ('-1','NaN','101'):
            rec={'home_aces':bad,'away_aces':'2','home_double_faults':'0','away_double_faults':'3'}
            self.assertIsNone(m.count4(rec))

    def test_source_sha_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in m.SOURCE_SHA:(Path(folder)/name).write_text('modified')
            with self.assertRaisesRegex(ValueError,'Source SHA mismatch'):
                m.source_rows(folder)

    def test_non_numeric_type_existing_quarantined(self):
        r,c=self.audit('{"p1_aces":"3"}')
        self.assertIsNone(c)
        self.assertEqual(r['counts']['conflicting_ace_df_matches'],1)

if __name__=='__main__':unittest.main()
