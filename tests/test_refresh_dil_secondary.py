import importlib.util
import json
import hashlib
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
import sys
sys.path.insert(0,str(ROOT if (ROOT/'refresh_dil_secondary.py').exists() else ROOT.parent/'scripts'))
import refresh_dil_secondary as op

class SecondaryOperatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.folder=self.root/'secondary';self.folder.mkdir()
        self.first=self.folder/'one.sqlite';self.first.write_bytes(b'SQLite-fixture-1')
        self.second=self.folder/'two.sqlite';self.second.write_bytes(b'SQLite-fixture-2')
        self.verified={'status':'VERIFIED_CURRENT_CDB_PARITY','source_release_manifest_sha256':'a'*64,'source_cdb_sha256':'b'*64}
    def tearDown(self):self.temp.cleanup()
    def test_activated_pointer_and_rollback_receipt(self):
        a=op.activate_secondary_pointer(self.folder,self.first,self.verified)
        self.assertTrue(a['secondary_only'])
        self.assertFalse(a['production_database_switch'])
        b=op.activate_secondary_pointer(self.folder,self.second,self.verified)
        self.assertEqual(b['filename'],'two.sqlite')
        backup=json.loads((self.folder/'previous-secondary.json').read_text())
        self.assertEqual(backup['filename'],'one.sqlite')
        self.assertEqual(json.loads((self.folder/'current-secondary.json').read_text())['filename'],'two.sqlite')
    def test_incomplete_parity_never_activates(self):
        with self.assertRaises(ValueError):
            op.activate_secondary_pointer(self.folder,self.first,{'status':'BLOCKED_CURRENT_CDB_PARITY'})
        self.assertFalse((self.folder/'current-secondary.json').exists())
    def test_end_to_end_operator_publishes_secondary_only_on_strict_pass(self):
        source=self.root/'source.sqlite';source.write_bytes(b'synthetic-old-dil')
        sha='e'*64;dilhash=hashlib.sha256(b'synthetic-new-dil').hexdigest()
        frozen={'tag_name':'tbt-data-v1','assets':[]}
        def fake_download(folder, before):
            folder.mkdir()
            return frozen
        def fake_export(folder,before,after,out):
            Path(out).write_bytes(b'cdb-only')
            Path(str(out)+'.receipt.json').write_text('{}')
            return {'export_sqlite_sha256':sha,'source_release_manifest_sha256':'f'*64}
        def fake_import(base,cdb,out,*args,**kw):
            Path(out).write_bytes(b'synthetic-new-dil')
            Path(str(out)+'.audit.json').write_text('\"import-checked\"')
            return {'result_dil_sha256':dilhash,
                    'data_gate':'ISOLATED_PARITY_IMPORT_PASS_PENDING_REVALIDATION',
                    'counts':{'provider_context_matches_shadowed':0}}
        def fake_audit(*a,**kw):
            return {'status':'VERIFIED_CURRENT_CDB_PARITY','secondary_promotion_allowed':True,
                    'source_release_manifest_sha256':'f'*64,'source_cdb_sha256':sha}
        with patch.object(op,'snapshot_metadata',return_value=frozen),\
             patch.object(op,'download_full_release',side_effect=fake_download),\
             patch.object(op.exporter,'build',side_effect=fake_export),\
             patch.object(op.importer,'reconcile',side_effect=fake_import),\
             patch.object(op.parity,'audit',side_effect=fake_audit),\
             patch.object(op,'verify_shadow_matches_original',return_value=0):
            result=op.refresh(source,self.root/'work',self.folder,activate=True)
        self.assertEqual(result['status'],'SECONDARY_ACTIVATED_VERIFIED')
        self.assertEqual((self.folder/'current-secondary.json').is_file(),True)
        self.assertEqual(source.read_bytes(),b'synthetic-old-dil')
        self.assertEqual(len(list(self.folder.glob('*.import.json'))),1)
    def test_operator_strict_parity_failure_leaves_active_version_unchanged(self):
        source=self.root/'source.sqlite';source.write_bytes(b'synthetic-old-dil')
        op.activate_secondary_pointer(self.folder,self.first,self.verified)
        frozen={'tag_name':'tbt-data-v1','assets':[]}
        def fake_download(folder,before):folder.mkdir();return frozen
        def fake_export(folder,before,after,out):
            Path(out).write_bytes(b'cdb');Path(str(out)+'.receipt.json').write_text('{}')
            return {'export_sqlite_sha256':'e'*64,'source_release_manifest_sha256':'f'*64}
        def fake_import(base,cdb,out,*args,**kw):
            Path(out).write_bytes(b'new');return {'result_dil_sha256':'d'*64,
                'data_gate':'BLOCKED_REVIEW_REQUIRED',
                'counts':{'provider_context_matches_shadowed':0}}
        bad={'status':'BLOCKED_CURRENT_CDB_PARITY','secondary_promotion_allowed':False,
             'source_release_manifest_sha256':'f'*64,'source_cdb_sha256':'e'*64}
        with patch.object(op,'snapshot_metadata',return_value=frozen),\
             patch.object(op,'download_full_release',side_effect=fake_download),\
             patch.object(op.exporter,'build',side_effect=fake_export),\
             patch.object(op.importer,'reconcile',side_effect=fake_import),\
             patch.object(op.parity,'audit',return_value=bad),\
             patch.object(op,'verify_shadow_matches_original',return_value=0):
            with self.assertRaisesRegex(ValueError,'DATA PARITY BLOCKED'):
                op.refresh(source,self.root/'failed-work',self.folder,activate=True)
        self.assertEqual(json.loads((self.folder/'current-secondary.json').read_text())['filename'],'one.sqlite')
        self.assertEqual(sorted(x.name for x in self.folder.glob('*.sqlite')),['one.sqlite','two.sqlite'])
    def test_new_shadow_provenance_must_match_original_source(self):
        source=self.root/'source-real.sqlite'
        candidate=self.root/'candidate-real.sqlite'
        for file in (source,candidate):
            with sqlite3.connect(file) as db:
                db.execute('CREATE TABLE canonical_matches(match_id TEXT PRIMARY KEY, provider_context_json TEXT)')
                db.execute('INSERT INTO canonical_matches VALUES (?,?)',('match-00001','{"venue":"old"}'))
                if file==candidate:
                    db.execute('''CREATE TABLE dil_cdb_provider_context_shadow(
                        match_id TEXT,source_sha256 TEXT,original_context_json TEXT,
                        original_context_sha256 TEXT,cdb_context_json TEXT,
                        merged_context_json TEXT,merged_context_sha256 TEXT)''')
                    original=json.dumps('{"venue":"old"}')
                    merged='{"venue":"new"}'
                    db.execute('INSERT INTO dil_cdb_provider_context_shadow VALUES(?,?,?,?,?,?,?)',
                        ('match-00001','a'*64,original,
                         hashlib.sha256(original.encode()).hexdigest(),
                         json.dumps(merged),merged,hashlib.sha256(merged.encode()).hexdigest()))
        self.assertEqual(op.verify_shadow_matches_original(source,candidate,'a'*64),1)
        self.assertEqual(op.verify_shadow_matches_original(candidate,candidate,'a'*64),0)
        with sqlite3.connect(source) as db:
            db.execute("UPDATE canonical_matches SET provider_context_json='{\"venue\":\"different\"}'")
        with self.assertRaisesRegex(AssertionError,'source proof mismatch'):
            op.verify_shadow_matches_original(source,candidate,'a'*64)

    def test_no_pointer_to_outside_file(self):
        outsider=self.root/'elsewhere.sqlite';outsider.write_bytes(b'foo')
        with self.assertRaises(ValueError):op.activate_secondary_pointer(self.folder,outsider,self.verified)
    def test_bad_previous_pointer_rejects_changes(self):
        (self.folder/'current-secondary.json').write_text(json.dumps({'filename':'notpresent.sqlite'}))
        with self.assertRaises(ValueError):op.activate_secondary_pointer(self.folder,self.first,self.verified)
    def test_existing_secondary_is_valid_next_base(self):
        op.activate_secondary_pointer(self.folder,self.first,self.verified)
        # Invalid nonexistent scratch never reaches remote, demonstrating next-base resolution.
        with patch.object(op,'snapshot_metadata',side_effect=RuntimeError('metadata-not-available')):
            with self.assertRaisesRegex(RuntimeError,'metadata-not-available'):
                op.refresh(None,self.root/'new-scratch',self.folder)
        self.assertEqual(json.loads((self.folder/'current-secondary.json').read_text())['filename'],'one.sqlite')
    def test_release_movement_block(self):
        fake={'tag_name':'tbt-data-v1','assets':[{'name':'history_manifest.json','size':99,'digest':'sha256:'+'a'*64,'id':1}]}
        moved={'tag_name':'tbt-data-v1','assets':[{'name':'history_manifest.json','size':99,'digest':'sha256:'+'b'*64,'id':1}]}
        with patch.object(op,'gh'),patch.object(op,'snapshot_metadata',return_value=moved):
            with self.assertRaisesRegex(ValueError,'moved'):
                op.download_full_release(self.root/'fresh',fake)
    def test_refuse_overlapping_dirs_without_private_download(self):
        source=self.root/'source.sqlite';source.write_bytes(b'SQLite')
        with self.assertRaisesRegex(ValueError,'separate'):
            op.refresh(source,self.root/'secondary'/'work',self.root/'secondary')

if __name__=='__main__':unittest.main()
