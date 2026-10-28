import hashlib,importlib.util,json,os,pathlib,sqlite3,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parent
SCRIPTS=(ROOT.parent/'scripts') if (ROOT.parent/'scripts'/'finalize_dil_from_cdb_v2.py').exists() else ROOT
s=importlib.util.spec_from_file_location('finalize',str(SCRIPTS/'finalize_dil_from_cdb_v2.py'))
f=importlib.util.module_from_spec(s);s.loader.exec_module(f)
e=importlib.util.spec_from_file_location('export',str(SCRIPTS/'build_current_cdb_compare.py'))
exp=importlib.util.module_from_spec(e);e.loader.exec_module(exp)
M='0'*64

class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();p=pathlib.Path(self.tmp.name);self.dil=p/'dil.sqlite';self.cdb=p/'cdb.sqlite';self.out=p/'out.sqlite'
        sql=exp.SCHEMA.replace('cdb_matches','canonical_matches')
        d=sqlite3.connect(self.dil);d.execute(sql)
        d.execute('CREATE TABLE dil_enrichment_compact (match_id TEXT PRIMARY KEY,json_metrics TEXT NOT NULL)')
        def row(mid,p1='p1',p2='p2',win='p1',status='finished',stats='{}'):
            return dict(match_id=mid,tour='atp',scheduled_at=1792000000000000000,player1_id=p1,player1_name='A',player2_id=p2,player2_name='B',surface='hard',tournament='T',tournament_id='t',tournament_level='250',round_name='R32',player1_rank=1,player2_rank=2,winner_id=win,status=status,best_of=3,indoor=0,stats_json=stats,provider_context_json=None,source_year=2026)
        self.row=row
        self.existing=row('known-2026-id-abcde',stats=json.dumps({'p1_aces':4}))
        d.execute('INSERT INTO canonical_matches ('+','.join(f.FIELDS)+') VALUES ('+','.join('?'*len(f.FIELDS))+')',[self.existing[k] for k in f.FIELDS])
        d.execute("INSERT INTO dil_enrichment_compact VALUES (?,?)",('known-2026-id-abcde',json.dumps({'p2_aces':1})))
        d.commit();d.close()
        c=sqlite3.connect(self.cdb);c.execute(sql.replace('canonical_matches','cdb_matches'))
        old=dict(self.existing,scheduled_at=1792000000,stats_json=json.dumps({'p1_aces':4,'p2_aces':1,'p1_double_faults':2}))
        new=row('new-2026-id-abcdef',p1='p3',p2='p4',win='p3',stats=json.dumps({'p1_aces':5}));new['scheduled_at']=1792000000
        review=row('review-2026-id-abc',p1='p5',p2='p6',win='p5',status='retired');review['scheduled_at']=1792000000
        for r in (old,new,review):c.execute('INSERT INTO cdb_matches ('+','.join(f.FIELDS)+') VALUES ('+','.join('?'*len(f.FIELDS))+')',[r[k] for k in f.FIELDS])
        c.commit();c.close()
        self.expected=f.sha256(self.cdb)
    def tearDown(self):self.tmp.cleanup()
    def test_reconcile_safe_and_idempotent(self):
        rep=f.reconcile(self.dil,self.cdb,self.out,self.expected,M)
        self.assertEqual(rep['counts']['new_matches'],2)
        self.assertEqual(rep['counts']['noncompleted_new_matches'],1)
        self.assertEqual(rep['counts']['stat_cells_filled'],1)
        self.assertEqual(rep['counts']['new_identity_review'],0)
        d=sqlite3.connect(self.out)
        self.assertEqual(d.execute('select count(*) from canonical_matches').fetchone()[0],3)
        self.assertEqual(json.loads(d.execute("select stats_json from canonical_matches where match_id='known-2026-id-abcde'").fetchone()[0]),{'p1_aces':4,'p1_double_faults':2})
        self.assertEqual(d.execute('select json_metrics from dil_enrichment_compact').fetchone()[0],'{"p2_aces": 1}')
        d.close()
        out2=self.out.parent/'out2.sqlite'
        # Already imported provenance persists; next pass fills no new cells.
        rep2=f.reconcile(self.out,self.cdb,out2,self.expected,M)
        self.assertEqual(rep2['counts']['new_matches'],0)
        self.assertEqual(rep2['counts']['stat_cells_filled'],0)
    def test_exact_timestamp_mismatch_is_not_promoted(self):
        c=sqlite3.connect(self.cdb)
        c.execute("UPDATE cdb_matches SET scheduled_at=scheduled_at+3600 WHERE match_id='known-2026-id-abcde'")
        c.commit();c.close()
        rep=f.reconcile(self.dil,self.cdb,self.out,f.sha256(self.cdb),M)
        self.assertEqual(rep['counts']['identity_review'],1)
        self.assertEqual(rep['counts']['stat_cells_filled'],0)
        self.assertEqual(rep['data_gate'],'BLOCKED_REVIEW_REQUIRED')

    def test_1970_nanoseconds_do_not_get_misdecoded(self):
        c=sqlite3.connect(self.cdb);d=sqlite3.connect(self.dil)
        mid='known-2026-id-abcde'
        # Tiny nanosecond epoch values defeat magnitude-based inference.
        d.execute('UPDATE canonical_matches SET scheduled_at=?,source_year=? WHERE match_id=?',
                 (43_200_000_000_000,1970,mid))
        c.execute('UPDATE cdb_matches SET scheduled_at=?,source_year=? WHERE match_id=?',
                  (43_200,1970,mid))
        d.commit();d.close();c.commit();c.close()
        rep=f.reconcile(self.dil,self.cdb,self.out,f.sha256(self.cdb),M)
        self.assertEqual(rep['counts']['identity_review'],0)
        self.assertEqual(rep['counts']['stat_cells_filled'],1)

    def test_duplicate_event_alternate_id_staged_only(self):
        c=sqlite3.connect(self.cdb)
        # A second CDB identifier points at the same event under different id.
        c.execute("UPDATE cdb_matches SET player1_id='p1', player2_id='p2',winner_id='p1' WHERE match_id='new-2026-id-abcdef'")
        c.commit();c.close()
        rep=f.reconcile(self.dil,self.cdb,self.out,f.sha256(self.cdb),M)
        self.assertEqual(rep['counts']['duplicate_event_review'],1)
        self.assertEqual(rep['counts']['new_matches'],1)
        self.assertEqual(rep['data_gate'],'BLOCKED_REVIEW_REQUIRED')
        d=sqlite3.connect(self.out)
        self.assertIsNone(d.execute("SELECT match_id FROM canonical_matches WHERE match_id='new-2026-id-abcdef'").fetchone())
        d.close()

    def test_null_only_metadata(self):
        d=sqlite3.connect(self.dil)
        d.execute("UPDATE canonical_matches SET player1_name=NULL WHERE match_id='known-2026-id-abcde'")
        d.commit();d.close()
        rep=f.reconcile(self.dil,self.cdb,self.out,self.expected,M)
        self.assertEqual(rep['counts']['metadata_fields_filled'],1)
        x=sqlite3.connect(self.out)
        self.assertEqual(x.execute("SELECT player1_name FROM canonical_matches WHERE match_id='known-2026-id-abcde'").fetchone()[0],'A')
        x.close()

    def test_valid_78_part_receipt_allows_isolated_gate(self):
        receipt=self.out.parent/'receipt.json'
        receipt.write_text(json.dumps({'schema':'BLINQ_FULL_CDB_COMPARE_EXPORT_V2',
          'status':'VERIFIED_LOCAL_CDB_SNAPSHOT_ONLY',
          'source_partition_count':78,'source_release_manifest_sha256':M,
          'export_sqlite_sha256':self.expected,'export_timestamp_unit':'UTC unix seconds',
          'source_matches':3,'cdb_mutated':False}))
        rep=f.reconcile(self.dil,self.cdb,self.out,self.expected,M,export_receipt=receipt)
        self.assertTrue(rep['source_export_attested'])
        self.assertEqual(rep['data_gate'],'ISOLATED_PARITY_IMPORT_PASS_PENDING_REVALIDATION')

    def test_tampered_receipt_rejected_before_copy(self):
        receipt=self.out.parent/'receipt-bad.json'
        receipt.write_text(json.dumps({'schema':'BLINQ_FULL_CDB_COMPARE_EXPORT_V2',
          'status':'VERIFIED_LOCAL_CDB_SNAPSHOT_ONLY',
          'source_partition_count':78,'source_release_manifest_sha256':M,
          'export_sqlite_sha256':'a'*64,'export_timestamp_unit':'UTC unix seconds',
          'source_matches':3,'cdb_mutated':False}))
        with self.assertRaisesRegex(ValueError,'immutable export receipt mismatch'):
            f.reconcile(self.dil,self.cdb,self.out,self.expected,M,export_receipt=receipt)
        self.assertFalse(self.out.exists())

    def test_provider_context_nested_null_only_merge(self):
        with sqlite3.connect(self.dil) as db:
            db.execute('UPDATE canonical_matches SET provider_context_json=? WHERE match_id=?',
               (json.dumps({'venue':{'city':'Bratislava','country':'SK'}}),'known-2026-id-abcde'))
        with sqlite3.connect(self.cdb) as db:
            db.execute('UPDATE cdb_matches SET provider_context_json=? WHERE match_id=?',
               (json.dumps({'venue':{'city':'Bratislava','court':'Center'}}),'known-2026-id-abcde'))
        r=f.reconcile(self.dil,self.cdb,self.out,f.sha256(self.cdb),M)
        self.assertEqual(r['counts']['metadata_fields_filled'],1)
        self.assertEqual(r['counts']['metadata_conflicts'],0)
        with sqlite3.connect(self.out) as db:
            obj=json.loads(db.execute('SELECT provider_context_json FROM canonical_matches WHERE match_id=?',
                                      ('known-2026-id-abcde',)).fetchone()[0])
            self.assertEqual(obj['venue'],{'city':'Bratislava','country':'SK','court':'Center'})
    def test_provider_context_conflict_is_losslessly_shadowed(self):
        mid='known-2026-id-abcde'
        original=json.dumps({'venue':{'city':'Bratislava','court':'Centre'},'dil_only':'retained'})
        authoritative=json.dumps({'venue':{'city':'Trnava','surface':None}})
        with sqlite3.connect(self.dil) as db:
            db.execute('UPDATE canonical_matches SET provider_context_json=? WHERE match_id=?',(original,mid))
        with sqlite3.connect(self.cdb) as db:
            db.execute('UPDATE cdb_matches SET provider_context_json=? WHERE match_id=?',(authoritative,mid))
        source_sha=f.sha256(self.cdb)
        r=f.reconcile(self.dil,self.cdb,self.out,source_sha,M)
        self.assertEqual(r['counts']['metadata_conflicts'],0)
        self.assertEqual(r['counts']['provider_context_conflicts_preserved'],1)
        self.assertEqual(r['counts']['provider_context_matches_shadowed'],1)
        with sqlite3.connect(self.out) as db:
            canonical=json.loads(db.execute(
                'SELECT provider_context_json FROM canonical_matches WHERE match_id=?',(mid,)).fetchone()[0])
            saved=db.execute('''SELECT original_context_json,original_context_sha256,
                        cdb_context_json,merged_context_json,merged_context_sha256 FROM dil_cdb_provider_context_shadow
                        WHERE match_id=? AND source_sha256=?''',(mid,source_sha)).fetchone()
            ledger=db.execute('''SELECT existing_json,incoming_json FROM
                dil_cdb_finalize_metadata_conflicts WHERE match_id=? AND
                field_name='provider_context_json.venue.city' ''',(mid,)).fetchone()
        self.assertEqual(canonical['venue'],{'city':'Trnava','court':'Centre'})
        self.assertEqual(canonical['dil_only'],'retained')
        self.assertEqual(json.loads(saved[0]),original)
        self.assertEqual(saved[1],f.shadow_hash(saved[0]))
        self.assertEqual(json.loads(saved[2]),authoritative)
        self.assertEqual(json.loads(saved[3]),canonical)
        self.assertEqual(saved[4],f.shadow_hash(saved[3]))
        self.assertEqual(json.loads(ledger[0]),'Bratislava')
        self.assertEqual(json.loads(ledger[1]),'Trnava')
        with sqlite3.connect(self.dil) as db:
            self.assertEqual(db.execute('SELECT provider_context_json FROM canonical_matches WHERE match_id=?',
                                        (mid,)).fetchone()[0],original)
        self.assertEqual(r['data_gate'],'ISOLATED_PARITY_IMPORT_PASS_PENDING_REVALIDATION')

    def test_empty_cdb_context_never_erases_existing_details(self):
        mid='known-2026-id-abcde'
        original=json.dumps({'venue':{'city':'Bratislava','court':'Centre'},'other':[1,2]})
        incoming=json.dumps({'venue':{'city':None},'other':[]})
        with sqlite3.connect(self.dil) as db:
            db.execute('UPDATE canonical_matches SET provider_context_json=? WHERE match_id=?',(original,mid))
        with sqlite3.connect(self.cdb) as db:
            db.execute('UPDATE cdb_matches SET provider_context_json=? WHERE match_id=?',(incoming,mid))
        r=f.reconcile(self.dil,self.cdb,self.out,f.sha256(self.cdb),M)
        with sqlite3.connect(self.out) as db:
            current=json.loads(db.execute('SELECT provider_context_json FROM canonical_matches WHERE match_id=?',
                (mid,)).fetchone()[0])
        self.assertEqual(current,json.loads(original))
        self.assertEqual(r['counts']['provider_context_conflicts_preserved'],0)

    def test_scalar_metadata_disagreement_is_retained_and_blocks(self):
        with sqlite3.connect(self.cdb) as db:
            db.execute("UPDATE cdb_matches SET tournament='Authoritative CDB' WHERE match_id='known-2026-id-abcde'")
        report=f.reconcile(self.dil,self.cdb,self.out,f.sha256(self.cdb),M)
        self.assertEqual(report['counts']['metadata_conflicts'],1)
        self.assertEqual(report['data_gate'],'BLOCKED_REVIEW_REQUIRED')
        with sqlite3.connect(self.out) as db:
            current=db.execute("SELECT tournament FROM canonical_matches WHERE match_id='known-2026-id-abcde'").fetchone()[0]
            stored=db.execute("SELECT existing_json,incoming_json,source_sha256 FROM dil_cdb_finalize_metadata_conflicts WHERE match_id='known-2026-id-abcde' AND field_name='tournament'").fetchone()
        self.assertEqual(current,'T')
        self.assertEqual(json.loads(stored[0]),'T')
        self.assertEqual(json.loads(stored[1]),'Authoritative CDB')
        self.assertEqual(stored[2],f.sha256(self.cdb))

    def test_provider_context_numeric_string_is_not_silently_equal(self):
        mid='known-2026-id-abcde'
        with sqlite3.connect(self.dil) as db:
            db.execute('UPDATE canonical_matches SET provider_context_json=? WHERE match_id=?', (json.dumps({'round_number':'3'}),mid))
        with sqlite3.connect(self.cdb) as db:
            db.execute('UPDATE cdb_matches SET provider_context_json=? WHERE match_id=?', (json.dumps({'round_number':3}),mid))
        r=f.reconcile(self.dil,self.cdb,self.out,f.sha256(self.cdb),M)
        self.assertEqual(r['counts']['metadata_conflicts'],0)
        self.assertEqual(r['counts']['provider_context_conflicts_preserved'],1)
        self.assertEqual(r['data_gate'],'ISOLATED_PARITY_IMPORT_PASS_PENDING_REVALIDATION')

    def test_metadata_unicode_whitespace_equivalence_is_non_destructive(self):
        with sqlite3.connect(self.dil) as db:
            db.execute("UPDATE canonical_matches SET tournament='Cafe\u0301   Open' WHERE match_id='known-2026-id-abcde'")
        with sqlite3.connect(self.cdb) as db:
            db.execute("UPDATE cdb_matches SET tournament='Café Open' WHERE match_id='known-2026-id-abcde'")
        report=f.reconcile(self.dil,self.cdb,self.out,f.sha256(self.cdb),M)
        self.assertEqual(report['counts']['metadata_conflicts'],0)
        with sqlite3.connect(self.out) as db:
            val=db.execute("SELECT tournament FROM canonical_matches WHERE match_id='known-2026-id-abcde'").fetchone()[0]
        self.assertEqual(val,'Cafe\u0301   Open')

    def test_refuse_wrong_cdb_sha(self):
        with self.assertRaises(ValueError): f.reconcile(self.dil,self.cdb,self.out,'9'*64,M)
        self.assertFalse(self.out.exists())
    def test_no_override_on_stat_conflict(self):
        c=sqlite3.connect(self.cdb)
        d=json.loads(c.execute("select stats_json from cdb_matches where match_id='known-2026-id-abcde'").fetchone()[0]);d['p1_aces']=99
        c.execute('update cdb_matches set stats_json=? where match_id=?',(json.dumps(d),'known-2026-id-abcde'));c.commit();c.close()
        rep=f.reconcile(self.dil,self.cdb,self.out,f.sha256(self.cdb),M)
        self.assertGreater(rep['counts']['stats_conflicts'],0)
        d=sqlite3.connect(self.out)
        self.assertEqual(json.loads(d.execute("select stats_json from canonical_matches where match_id='known-2026-id-abcde'").fetchone()[0])['p1_aces'],4)
        d.close()
    def test_existing_core_conflict_quarantined(self):
        c=sqlite3.connect(self.cdb)
        c.execute("update cdb_matches set player2_id='wrongplayer' where match_id='known-2026-id-abcde'");c.commit();c.close()
        rep=f.reconcile(self.dil,self.cdb,self.out,f.sha256(self.cdb),M)
        self.assertEqual(rep['counts']['identity_review'],1)
        self.assertEqual(rep['counts']['stat_cells_filled'],0)

if __name__=='__main__':unittest.main(verbosity=2)