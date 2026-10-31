import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_dil_to_cdb_null_candidates import scan,valid_field

class ReverseTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.cdb=self.root/'cdb.sqlite'
        self.dil=self.root/'dil.sqlite'
        with sqlite3.connect(self.cdb) as db:
            db.execute('CREATE TABLE cdb_matches(match_id TEXT PRIMARY KEY,stats_json TEXT)')
            db.execute('INSERT INTO cdb_matches VALUES(?,?)',('abc123',json.dumps({'p1_aces':None,'p2_aces':2})))
        with sqlite3.connect(self.dil) as db:
            db.execute('CREATE TABLE canonical_matches(match_id TEXT PRIMARY KEY,tour TEXT,source_year INTEGER,stats_json TEXT)')
            db.execute('CREATE TABLE dil_enrichment_compact(match_id TEXT PRIMARY KEY,json_metrics TEXT)')
            db.execute('INSERT INTO canonical_matches VALUES(?,?,?,?)',('abc123','atp',2024,json.dumps({'p1_aces':4,'p1_return_points_won':.25,'p2_aces':2})))
            db.execute('INSERT INTO dil_enrichment_compact VALUES(?,?)',('abc123',json.dumps({'p1_return_points_won':.25,'p1_double_faults':3})))
        from audit_dil_to_cdb_null_candidates import sha256
        self.sha=sha256(self.cdb)
        self.receipt=self.root/'receipt.json'
        self.receipt.write_text(json.dumps({'schema':'BLINQ_FULL_CDB_COMPARE_EXPORT_V2','status':'VERIFIED_LOCAL_CDB_SNAPSHOT_ONLY','source_partition_count':78,'source_release_manifest_sha256':'d'*64,'export_sqlite_sha256':self.sha}))
        self.parity=self.root/'parity.json'
        self.parity.write_text(json.dumps({'status':'VERIFIED_CURRENT_CDB_PARITY','full_integrity_check':True,'secondary_promotion_allowed':True,'source_cdb_sha256':self.sha,'source_release_manifest_sha256':'d'*64}))

    def run_audit(self):
        return scan(self.cdb,self.dil,self.receipt,self.parity)

    def test_null_only_stats_are_not_import_authorized(self):
        result=self.run_audit()
        self.assertEqual(result['counts']['type_valid_cdb_null_cells_needing_provenance'],3)
        self.assertEqual(result['counts']['already_populated_cdb_cells'],1)
        self.assertEqual(result['ready_for_existing_cdb_writer'],0)
        self.assertFalse(result['canonical_write_authorized'])
        self.assertNotIn('abc123',json.dumps(result))

    def test_overlay_conflict_is_quarantined(self):
        with sqlite3.connect(self.dil) as db:
            db.execute('UPDATE dil_enrichment_compact SET json_metrics=?', (json.dumps({'p1_return_points_won':.3,'p1_double_faults':3}),))
        x=self.run_audit()
        self.assertEqual(x['counts']['intra_dil_overlay_conflicts'],1)
        self.assertEqual(x['counts']['type_valid_cdb_null_cells_needing_provenance'],2)

    def test_rate_above_one_not_a_candidate(self):
        with sqlite3.connect(self.dil) as db:
            db.execute('UPDATE dil_enrichment_compact SET json_metrics=?',(json.dumps({'p1_return_points_won':5,'p1_double_faults':3}),))
        self.assertEqual(self.run_audit()['counts']['invalid_or_unsupported_null_cells'],1)

    def test_unsupported_extra_count_not_authorized(self):
        with sqlite3.connect(self.dil) as db:
            db.execute('UPDATE dil_enrichment_compact SET json_metrics=?',(json.dumps({'p1_break_points_won_count':5}),))
        self.assertEqual(self.run_audit()['counts']['invalid_or_unsupported_null_cells'],1)

    def test_mismatched_cdb_sha_fails(self):
        v=json.loads(self.receipt.read_text());v['export_sqlite_sha256']='0'*64;self.receipt.write_text(json.dumps(v))
        with self.assertRaisesRegex(ValueError,'not attested'):
            self.run_audit()

    def test_unverified_parity_fails(self):
        v=json.loads(self.parity.read_text());v['full_integrity_check']=False;self.parity.write_text(json.dumps(v))
        with self.assertRaisesRegex(ValueError,'not attested'):
            self.run_audit()

    def test_empty_join_fails(self):
        with sqlite3.connect(self.dil) as db:db.execute('UPDATE canonical_matches SET match_id=?',('other',))
        with self.assertRaisesRegex(ValueError,'Empty join'):
            self.run_audit()

    def test_rate_and_counts_type_constraints(self):
        self.assertTrue(valid_field('p1_return_points_won',0.75))
        self.assertTrue(valid_field('p2_aces',0))
        self.assertFalse(valid_field('p1_return_points_won',3))
        self.assertFalse(valid_field('p2_aces',2.5))
        self.assertFalse(valid_field('p2_aces',True))
        self.assertFalse(valid_field('p1_break_points_won_count',4))

if __name__=='__main__':unittest.main()
