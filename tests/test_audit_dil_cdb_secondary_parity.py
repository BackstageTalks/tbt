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
from finalize_dil_from_cdb_v2 import FIELDS, reconcile
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
    def test_per_field_conflict_accounting_without_private_values(self):
        with sqlite3.connect(self.dil) as db:
            db.execute("UPDATE canonical_matches SET tournament='t',round_name='Wrong round'")
        r=self.check(full_integrity=True)
        self.assertEqual(r['counts']['cdb_metadata_conflicting_fields'],2)
        self.assertEqual(r['counts']['cdb_metadata_conflicting_field_tournament'],1)
        self.assertEqual(r['counts']['cdb_metadata_conflicting_field_round_name'],1)
        self.assertEqual(r['counts']['cdb_metadata_casefold_candidate_tournament'],1)
        self.assertFalse(r['secondary_promotion_allowed'])

    def test_provider_context_bool_and_zero_do_not_compare_equal(self):
        with sqlite3.connect(self.cdb) as db:
            db.execute('UPDATE cdb_matches SET provider_context_json=?',(json.dumps({'venue':{'indoor':False}}),))
        with sqlite3.connect(self.dil) as db:
            db.execute('UPDATE canonical_matches SET provider_context_json=?',(json.dumps({'venue':{'indoor':0}}),))
        self.sha=audit.file_sha256(self.cdb)
        rc=json.loads(self.receipt.read_text());rc['export_sqlite_sha256']=self.sha
        self.receipt.write_text(json.dumps(rc))
        r=self.check(full_integrity=True)
        self.assertEqual(r['counts']['cdb_metadata_conflicting_field_provider_context_json'],1)
        self.assertFalse(r['secondary_promotion_allowed'])

    def test_unicode_and_space_normalization_is_equivalent(self):
        with sqlite3.connect(self.cdb) as db:
            db.execute("UPDATE cdb_matches SET tournament='Café Open'")
        with sqlite3.connect(self.dil) as db:
            db.execute("UPDATE canonical_matches SET tournament='Cafe\u0301  Open'")
        self.sha=audit.file_sha256(self.cdb)
        rc=json.loads(self.receipt.read_text());rc['export_sqlite_sha256']=self.sha
        self.receipt.write_text(json.dumps(rc))
        r=self.check(full_integrity=True)
        self.assertEqual(r['counts'].get('cdb_metadata_conflicting_fields',0),0)
        self.assertEqual(r['counts']['cdb_metadata_normalized_equal_field_tournament'],1)

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
    def test_lossless_context_resolution_passes_independent_full_parity_and_second_sync(self):
        mid=self.one['match_id']
        with sqlite3.connect(self.dil) as db:
            db.execute('UPDATE canonical_matches SET provider_context_json=?',
                (json.dumps({'venue':{'city':'Bratislava','centre_court':'yes'},'dil_only':'KEEP'}),))
        with sqlite3.connect(self.cdb) as db:
            db.execute('UPDATE cdb_matches SET provider_context_json=?',
                (json.dumps({'venue':{'city':'Trnava','unpopulated':None}}),))
        self.sha=audit.file_sha256(self.cdb)
        rc=json.loads(self.receipt.read_text())
        rc.update({'export_sqlite_sha256':self.sha,'export_timestamp_unit':'UTC unix seconds',
                   'cdb_mutated':False})
        self.receipt.write_text(json.dumps(rc))
        candidate=self.dil.parent/'new-secondary.sqlite'
        report=reconcile(self.dil,self.cdb,candidate,self.sha,'1'*64,export_receipt=self.receipt)
        self.assertEqual(report['counts']['provider_context_matches_shadowed'],1)
        self.assertEqual(report['counts']['metadata_conflicts'],0)
        verified=audit.audit(self.cdb,candidate,self.sha,attest=self.receipt,full_integrity=True)
        self.assertTrue(verified['secondary_promotion_allowed'])
        self.assertEqual(verified['counts']['provider_context_shadows_verified'],1)
        self.assertEqual(verified['counts']['provider_context_current_source_shadows_verified'],1)
        second=self.dil.parent/'second-secondary.sqlite'
        report2=reconcile(candidate,self.cdb,second,self.sha,'1'*64,export_receipt=self.receipt)
        self.assertEqual(report2['counts']['provider_context_matches_shadowed'],0)
        self.assertTrue(audit.audit(self.cdb,second,self.sha,
                                   attest=self.receipt,full_integrity=True)['secondary_promotion_allowed'])
        # Simulate tomorrow's authoritative source release: old shadows must
        # still be verified against their immutable historical snapshot.
        with sqlite3.connect(self.cdb) as db:
            db.execute('UPDATE cdb_matches SET provider_context_json=?',
                (json.dumps({'venue':{'city':'Žilina'}}),))
        self.sha=audit.file_sha256(self.cdb)
        rc=json.loads(self.receipt.read_text())
        rc['export_sqlite_sha256']=self.sha
        self.receipt.write_text(json.dumps(rc))
        third=self.dil.parent/'third-secondary.sqlite'
        report3=reconcile(second,self.cdb,third,self.sha,'1'*64,export_receipt=self.receipt)
        self.assertEqual(report3['counts']['provider_context_matches_shadowed'],1)
        with sqlite3.connect(third) as db:
            versions=db.execute('SELECT COUNT(*) FROM dil_cdb_provider_context_shadow').fetchone()[0]
            current3=json.loads(db.execute('SELECT provider_context_json FROM canonical_matches WHERE match_id=?',
                              (mid,)).fetchone()[0])
        self.assertEqual(versions,2)
        self.assertEqual(current3['venue']['city'],'Žilina')
        self.assertTrue(audit.audit(self.cdb,third,self.sha,
                                    attest=self.receipt,full_integrity=True)['secondary_promotion_allowed'])
        with sqlite3.connect(second) as db:
            current=json.loads(db.execute('SELECT provider_context_json FROM canonical_matches WHERE match_id=?',
                                        (mid,)).fetchone()[0])
            self.assertEqual(current['venue']['city'],'Trnava')
            self.assertEqual(current['venue']['centre_court'],'yes')
            self.assertEqual(current['dil_only'],'KEEP')
            db.execute("UPDATE dil_cdb_provider_context_shadow SET original_context_json='tampered'")
        rejected=audit.audit(self.cdb,second,self.sha,attest=self.receipt,full_integrity=True)
        self.assertFalse(rejected['secondary_promotion_allowed'])
        self.assertEqual(rejected['counts']['provider_context_shadow_invalid_rows'],1)

    def test_no_unattested_parity(self):
        with self.assertRaises(ValueError):audit.audit(self.cdb,self.dil,self.sha)

if __name__=='__main__':unittest.main()