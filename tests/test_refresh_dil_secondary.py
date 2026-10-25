import importlib.util
import json
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
        sha='e'*64;dilhash='d'*64
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
            return {'result_dil_sha256':dilhash,
                    'data_gate':'ISOLATED_PARITY_IMPORT_PASS_PENDING_REVALIDATION'}
        def fake_audit(*a,**kw):
            return {'status':'VERIFIED_CURRENT_CDB_PARITY','secondary_promotion_allowed':True,
                    'source_release_manifest_sha256':'f'*64,'source_cdb_sha256':sha}
        with patch.object(op,'snapshot_metadata',return_value=frozen),\
             patch.object(op,'download_full_release',side_effect=fake_download),\
             patch.object(op.exporter,'build',side_effect=fake_export),\
             patch.object(op.importer,'reconcile',side_effect=fake_import),\
             patch.object(op.parity,'audit',side_effect=fake_audit):
            result=op.refresh(source,self.root/'work',self.folder,activate=True)
        self.assertEqual(result['status'],'SECONDARY_ACTIVATED_VERIFIED')
        self.assertEqual((self.folder/'current-secondary.json').is_file(),True)
        self.assertEqual(source.read_bytes(),b'synthetic-old-dil')
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
                'data_gate':'BLOCKED_REVIEW_REQUIRED'}
        bad={'status':'BLOCKED_CURRENT_CDB_PARITY','secondary_promotion_allowed':False,
             'source_release_manifest_sha256':'f'*64,'source_cdb_sha256':'e'*64}
        with patch.object(op,'snapshot_metadata',return_value=frozen),\
             patch.object(op,'download_full_release',side_effect=fake_download),\
             patch.object(op.exporter,'build',side_effect=fake_export),\
             patch.object(op.importer,'reconcile',side_effect=fake_import),\
             patch.object(op.parity,'audit',return_value=bad):
            with self.assertRaisesRegex(ValueError,'DATA PARITY BLOCKED'):
                op.refresh(source,self.root/'failed-work',self.folder,activate=True)
        self.assertEqual(json.loads((self.folder/'current-secondary.json').read_text())['filename'],'one.sqlite')
        self.assertEqual(sorted(x.name for x in self.folder.glob('*.sqlite')),['one.sqlite','two.sqlite'])
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
