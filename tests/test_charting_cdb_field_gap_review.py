import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('review',Path(__file__).resolve().parents[1]/'scripts'/'charting_cdb_field_gap_review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)

class FieldGapReviewTests(unittest.TestCase):
    def fixture(self,root,existing=None):
        root=Path(root)
        source_id='20260109-M-Foo-R16-Player_A-Player_B'
        source={source_id:dict(id=source_id,tour='atp',date='20260109',tournament='Foo',round='R16',surface='Hard',players=['Player A','Player B'])}
        (root/'matches.json').write_text(json.dumps(source))
        players=[]
        # A: 10 serve points, 6 won, 12 received return, 4 return won.
        # B: 12 serve points, 8 won, 10 received return, 4 return won.
        entries=[('Player A',dict(serve_pts=10,first_in=6,second_in=4,first_won=4,second_won=2,aces=2,dfs=1,return_pts=12,return_pts_won=4,bk_pts=3,bp_saved=1)),
                 ('Player B',dict(serve_pts=12,first_in=7,second_in=5,first_won=5,second_won=3,aces=1,dfs=0,return_pts=10,return_pts_won=4,bk_pts=2,bp_saved=1))]
        for name,s in entries:
            slug=name.lower().replace(' ','-')
            rel=f'profiles/atp/atp-{slug}.json.gz'
            dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            profile=dict(player_id=f'atp-{slug}',name=name,tour='atp',match_ids=[source_id],overview_by_match=[dict(match_id=source_id,date='20260109',surface='Hard',stats=s)])
            with gzip.open(dest,'wt') as f:json.dump(profile,f)
            players.append(dict(name=name,tour='atp',path=rel,player_id=f'atp-{slug}'))
        (root/'players.json').write_text(json.dumps(players))
        crosswalk=root/'crosswalk.jsonl'
        crosswalk.write_text(json.dumps(dict(status='CANDIDATE_COMPOUND_ONLY',source_match_id=source_id,canonical_match_id_candidate='canon:1',canonical_player_ids_candidate=['a-id','b-id'],source_side_to_canonical_side=[1,2]))+'\n')
        canon=root/'cdb.jsonl'
        if existing is None:existing={'p1_aces':2,'p2_aces':1,'p1_service_points_won':0.6}
        canon.write_text(json.dumps(dict(match_id='canon:1',player1_id='a-id',player2_id='b-id',stats_json=json.dumps(existing)))+'\n')
        return root/'matches.json',root/'players.json',crosswalk,root,canon

    def test_full_points_and_null_gaps_no_writes(self):
        with tempfile.TemporaryDirectory() as t:
            args=self.fixture(t)
            manifest=review.run(*args[:3],args[3],[args[4]],Path(t)/'out')
            self.assertEqual(manifest['canonical_cdb_writes'],0)
            self.assertFalse(manifest['independent_event_and_both_player_id_proof'])
            self.assertEqual(manifest['counts']['RESEARCH_FIELD_GAPS_PENDING_EVENT_ID_PROOF'],1)
            self.assertGreater(manifest['counts']['missing_candidate_cells_not_approved'],2)
            self.assertEqual(manifest['counts']['matching_canonical_cells'],3)
            self.assertFalse(any(r['write_authorized'] for r in review.rows(Path(t)/'out/field_gap_research_only.jsonl.gz')))
            # These 22 internally balanced points could be only a match subset.
            self.assertFalse(manifest['whole_match_coverage_verified'])
            for row in review.rows(Path(t)/'out/field_gap_research_only.jsonl.gz'):
                self.assertFalse(row['whole_match_coverage_verified'])
                self.assertIn('independent_whole_match_coverage',row['remaining_evidence'])
    def test_canonical_conflict_quarantined(self):
        with tempfile.TemporaryDirectory() as t:
            args=self.fixture(t,{'p1_aces':9})
            m=review.run(*args[:3],args[3],[args[4]],Path(t)/'out')
            self.assertEqual(m['counts']['QUARANTINE_EXISTING_STATS_CONFLICT'],1)
            self.assertEqual(m['counts'].get('missing_candidate_cells_not_approved',0),0)
    def test_missing_profile_quarantined(self):
        with tempfile.TemporaryDirectory() as t:
            args=self.fixture(t)
            (Path(t)/'profiles/atp/atp-player-b.json.gz').unlink()
            m=review.run(*args[:3],args[3],[args[4]],Path(t)/'out')
            self.assertEqual(m['counts']['QUARANTINE_SOURCE_OR_CDB_INCONSISTENT'],1)
    def test_snapshot_drift_blocks_before_looking_at_stats(self):
        with tempfile.TemporaryDirectory() as t:
            args=self.fixture(t)
            pins=Path(t)/'sha.json';pins.write_text(json.dumps({'cdb.jsonl':'0'*64}))
            with self.assertRaisesRegex(ValueError,'drift'):
                review.run(*args[:3],args[3],[args[4]],Path(t)/'out',pins)
    def test_point_balance_failure(self):
        with tempfile.TemporaryDirectory() as t:
            args=self.fixture(t)
            p=Path(t)/'profiles/atp/atp-player-b.json.gz'
            with gzip.open(p,'rt') as f:profile=json.load(f)
            profile['overview_by_match'][0]['stats']['return_pts_won']=5
            with gzip.open(p,'wt') as f:json.dump(profile,f)
            m=review.run(*args[:3],args[3],[args[4]],Path(t)/'out')
            self.assertEqual(m['counts']['QUARANTINE_SOURCE_OR_CDB_INCONSISTENT'],1)
if __name__=='__main__':unittest.main()
