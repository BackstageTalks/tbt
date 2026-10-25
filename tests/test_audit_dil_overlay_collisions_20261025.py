import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'scripts' if (Path(__file__).resolve().parent.parent/'scripts').exists() else Path(__file__).resolve().parent))
import audit_dil_overlay_collisions_20261025 as probe


class FullDILOverlayCollisionTests(unittest.TestCase):
    def fixture(self, canon, overlay):
        tmp=tempfile.TemporaryDirectory()
        path=Path(tmp.name)/'source.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE canonical_matches(match_id TEXT PRIMARY KEY,stats_json TEXT)')
            db.execute('CREATE TABLE dil_enrichment_compact(match_id TEXT PRIMARY KEY,json_metrics TEXT)')
            for k,v in canon.items(): db.execute('INSERT INTO canonical_matches VALUES(?,?)',(k,json.dumps(v)))
            for k,v in overlay.items(): db.execute('INSERT INTO dil_enrichment_compact VALUES(?,?)',(k,json.dumps(v)))
        return tmp,path

    def test_disjoint_names_and_no_orphans_pass(self):
        tmp,path=self.fixture({'m':{'ace':2}},{'m':{'tbi_rate':0.42}})
        try:
            a=probe.audit(path)
            self.assertEqual(a['status'],'PASS')
            self.assertEqual(a['counts']['shared_metric_keys'],0)
            self.assertEqual(a['counts']['orphan_overlay_rows'],0)
        finally:tmp.cleanup()

    def test_conflicting_same_metric_blocks(self):
        tmp,path=self.fixture({'m':{'ace':2}},{'m':{'ace':3}})
        try:
            a=probe.audit(path)
            self.assertEqual(a['status'],'REVIEW_REQUIRED')
            self.assertEqual(a['counts']['conflicting_nonnull_metric_cells'],1)
            self.assertEqual(a['counts']['matches_with_collision'],1)
            self.assertEqual(a['top_collision_stat_names'],[('ace',1)])
        finally:tmp.cleanup()

    def test_matching_same_metric_is_not_collision(self):
        tmp,path=self.fixture({'m':{'ace':2}},{'m':{'ace':2.0}})
        try:
            a=probe.audit(path)
            self.assertEqual(a['status'],'PASS')
            self.assertEqual(a['counts']['same_value_metric_cells'],1)
        finally:tmp.cleanup()

    def test_orphan_overlay_blocks(self):
        tmp,path=self.fixture({'m':{}},{'orphan':{'derived':1}})
        try:
            a=probe.audit(path)
            self.assertEqual(a['status'],'REVIEW_REQUIRED')
            self.assertEqual(a['counts']['orphan_overlay_rows'],1)
        finally:tmp.cleanup()

    def test_null_overlap_recorded_without_false_conflict(self):
        tmp,path=self.fixture({'m':{'ace':None}},{'m':{'ace':3}})
        try:
            a=probe.audit(path)
            self.assertEqual(a['counts']['null_metric_overlap'],1)
            self.assertEqual(a['counts'].get('conflicting_nonnull_metric_cells',0),0)
        finally:tmp.cleanup()

if __name__=='__main__':unittest.main()