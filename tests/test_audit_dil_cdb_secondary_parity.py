import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
for pkg in (HERE, HERE.parent/'scripts'):
    if (pkg/'audit_dil_cdb_secondary_parity.py').is_file():
        import sys
        sys.path.insert(0,str(pkg))
        break
import audit_dil_cdb_secondary_parity as audit
from finalize_dil_from_cdb_v2 import FIELDS
from build_current_cdb_compare import SCHEMA

class SecondaryParityTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        root=Path(self.t.name)
        self.cdb=root/'cdb.sqlite';self.dil=root/'dil.sqlite';self.receipt=root/'receipt.json'
        ts=1792000000
        self.one={'match_id':'canonical-match-id-0001','tour':'atp','scheduled_at':ts,
                  'player1_id':'p1','player1_name':'A','player2_id':'p2','player2_name':'B',
                  'winner_id':'p1','surface':'hard','status':'finished','source_year':2026,
                  'stats_json':json.dumps({'p1_aces':4,'p2_aces':2}),
                  'tournament':'T','tournament_id':'T1','tournament_level':'250',
                  'round_name':'R32','player1_rank':1,'player2_rank':2,'best_of':3,
                  'indoor':0,'provider_context_json':'{}'}
        with sqlite3.connect(self.cdb) as db:
            db.execute(SCHEMA)
            db.execute('INSERT INTO cdb_matches ('+','.join(FIELDS)+') VALUES ('+','.join('?'*len(FIELDS))+')',[self.one[k] for k in FIELDS])
        with sqlite3.connect(self.dil) as db:
            db.execute(SCHEMA.replace('cdb_matches','canonical_matches'))
            record={**self.one,'scheduled_at':ts*10**9}
            db.execute('INSERT INTO canonical_matches ('+','.join(FIELDS)+') VALUES ('+','.join('?'*len(FIELDS))+')',[record[k] for k in FIELDS])
            db.execute('CREATE TABLE dil_enrichment_compact (match_id TEXT PRIMARY KEY,json_metrics TEXT NOT NULL)')
        self.sha=audit.file_sha256(self.cdb)
        self.receipt.write_text(json.dumps({'schema':'BLINQ_FULL_CDB_COMPARE_EXPORT_V2','status':'VERIFIED_LOCAL_CDB_SNAPSHOT_ONLY',
              'source_partition_count':78,'source_release_manifest_sha256':'1'*64,'export_sqlite_sha256':self.sha,'source_matches':1}))
    def tearDown(self):self.t.cleanup()
    def check(self,**kw):return audit.audit(self.cdb,self.dil,self.sha,attest=self.receipt,**kw)
    def test_exact_match_passes(self):
        r=self.check(full_integrity=True)
        self.assertEqual(r['status'],'VERIFIED_CURRENT_CDB_PARITY')
        self.assertEqual(r['counts']['cdb_stat_cells_matched'],2)
        self.assertTrue(r['secondary_promotion_allowed'])
    def test_missing_stat_blocks(self):
        with sqlite3.connect(self.dil) as db:db.execute("UPDATE canonical_matches SET stats_json='{}'")
        r=self.check()
        self.assertEqual(r['status'],'BLOCKED_CURRENT_CDB_PARITY')
        self.assertEqual(r['counts']['cdb_stat_cells_missing_effective_dil'],2)
    def test_overlay_satisfies_missing_stat(self):
        with sqlite3.connect(self.dil) as db:
            db.execute("UPDATE canonical_matches SET stats_json='{}'")
            db.execute('INSERT INTO dil_enrichment_compact VALUES (?,?)',(self.one['match_id'],json.dumps({'p1_aces':4,'p2_aces':2})))
        self.assertTrue(self.check(full_integrity=True)['secondary_promotion_allowed'])
    def test_conflict_blocks_even_when_not_null(self):
        with sqlite3.connect(self.dil) as db:db.execute('UPDATE canonical_matches SET stats_json=?',(json.dumps({'p1_aces':12,'p2_aces':2}),))
        r=self.check()
        self.assertEqual(r['counts']['cdb_stat_cells_conflicting_effective_dil'],1)
    def test_source_only_null_provider_context_is_not_a_missing_value(self):
        with sqlite3.connect(self.cdb) as db:
            db.execute('UPDATE cdb_matches SET provider_context_json=?',
                       (json.dumps({'venue':{'region':None},'unknown':None}),))
        self.sha=audit.file_sha256(self.cdb)
        rc=json.loads(self.receipt.read_text());rc['export_sqlite_sha256']=self.sha
        self.receipt.write_text(json.dumps(rc))
        self.assertTrue(self.check(full_integrity=True)['secondary_promotion_allowed'])
    def test_invalid_dil_only_rate_blocks_even_when_cdb_cells_match(self):
        with sqlite3.connect(self.dil) as db:
            db.execute('UPDATE canonical_matches SET stats_json=?',
                       (json.dumps({'p1_aces':4,'p2_aces':2,'p1_service_points_won':70}),))
        r=self.check(full_integrity=True)
        self.assertEqual(r['counts']['invalid_dil_canonical_metric_cells'],1)
        self.assertFalse(r['secondary_promotion_allowed'])
    def test_nonfinite_dil_overlay_blocks(self):
        with sqlite3.connect(self.dil) as db:
            db.execute('INSERT INTO dil_enrichment_compact VALUES (?,?)',
                       (self.one['match_id'],json.dumps({'p2_double_faults':float('nan')})))
        r=self.check(full_integrity=True)
        self.assertEqual(r['counts']['invalid_dil_overlay_metric_cells'],1)
    def test_cdb_metadata_missing_blocks(self):
        with sqlite3.connect(self.dil) as db:
            db.execute('UPDATE canonical_matches SET tournament=NULL')
        r=self.check(full_integrity=True)
        self.assertEqual(r['counts']['cdb_metadata_missing_fields'],1)
        self.assertFalse(r['secondary_promotion_allowed'])
    def test_cdb_metadata_conflict_blocks(self):
        with sqlite3.connect(self.dil) as db:
            db.execute("UPDATE canonical_matches SET tournament='Wrong tournament'")
        r=self.check(full_integrity=True)
        self.assertEqual(r['counts']['cdb_metadata_conflicting_fields'],1)
    def test_extra_dil_provider_context_is_allowed(self):
        with sqlite3.connect(self.cdb) as db:
            db.execute('UPDATE cdb_matches SET provider_context_json=?',(json.dumps({'venue':{'city':'Paris'}}),))
        with sqlite3.connect(self.dil) as db:
            db.execute('UPDATE canonical_matches SET provider_context_json=?',
                       (json.dumps({'venue':{'city':'Paris','floor':'1'},'dil_only_source':'ok'}),))
        self.sha=audit.file_sha256(self.cdb)
        rc=json.loads(self.receipt.read_text());rc['export_sqlite_sha256']=self.sha
        self.receipt.write_text(json.dumps(rc))
        self.assertTrue(self.check(full_integrity=True)['secondary_promotion_allowed'])
    def test_core_mismatch_blocks(self):
        with sqlite3.connect(self.dil) as db:db.execute("UPDATE canonical_matches SET surface='clay'")
        self.assertEqual(self.check()['counts']['core_mismatched_matches'],1)
    def test_missing_id_blocks(self):
        with sqlite3.connect(self.dil) as db:db.execute('DELETE FROM canonical_matches')
        self.assertEqual(self.check()['counts']['missing_cdb_match_ids_in_dil'],1)
    def test_dil_only_id_blocks(self):
        other={**self.one,'match_id':'another-canonical-id-0022','scheduled_at':self.one['scheduled_at']*10**9}
        with sqlite3.connect(self.dil) as db:
            db.execute('INSERT INTO canonical_matches ('+','.join(FIELDS)+') VALUES ('+','.join('?'*len(FIELDS))+')',[other[k] for k in FIELDS])
        self.assertEqual(self.check()['counts']['dil_canonical_ids_not_in_cdb'],1)
    def test_quick_check_only_never_promotes(self):
        r=self.check()
        self.assertEqual(r['status'],'PRELIMINARY_CHECK_ONLY')
        self.assertFalse(r['secondary_promotion_allowed'])
    def test_hash_tamper_fails_closed(self):
        with self.assertRaises(ValueError):audit.audit(self.cdb,self.dil,'f'*64,attest=self.receipt)
    def test_no_unattested_parity(self):
        with self.assertRaises(ValueError):audit.audit(self.cdb,self.dil,self.sha)

if __name__=='__main__':unittest.main()