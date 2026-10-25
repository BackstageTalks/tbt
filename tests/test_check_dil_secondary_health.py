import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import check_dil_secondary_health as health


class TestSecondaryHealth(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.release = 'a'*64
        self.cdb = 'b'*64
        self.create('first.sqlite')
        self.pointer('first.sqlite')

    def tearDown(self): self.temp.cleanup()

    def create(self, name):
        path = self.root / name
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE canonical_matches (match_id TEXT PRIMARY KEY)')
            db.execute('INSERT INTO canonical_matches VALUES (?)', ('match-1',))
        importer = {
            'schema': health.IMPORT_SCHEMA, 'status': 'ISOLATED_VERIFIED_NOT_PRODUCTION',
            'data_gate': 'ISOLATED_PARITY_IMPORT_PASS_PENDING_REVALIDATION',
            'source_export_attested': True, 'production_promoted': False,
            'cdb_modified': False, 'model_untouched': True,
            'source_cdb_sha256': self.cdb, 'source_release_manifest_sha256': self.release,
            'canonical_matches_after': 1, 'result_dil_sha256': health.file_sha256(path),
            'quick_check':'ok','provenance_missing':0,'counts':{'rows_cdb':1}}
        parity = {'schema': health.PARITY_SCHEMA, 'status': 'VERIFIED_CURRENT_CDB_PARITY',
                  'secondary_promotion_allowed': True, 'full_integrity_check': True,
                  'production_cdb_modified': False, 'production_cdb_replaced': False,
                  'model_training_authorized': False, 'source_cdb_sha256': self.cdb,
                  'source_release_manifest_sha256': self.release,
                  'counts': {'cdb_matches': 1, 'dil_matches': 1, 'cdb_populated_stat_cells': 2}}
        (self.root / (name+'.import.json')).write_text(json.dumps(importer))
        (self.root / (name+'.parity.json')).write_text(json.dumps(parity))

    def pointer(self,name,previous=False):
        p = {'schema': health.SCHEMA, 'filename': name, 'secondary_only': True,
             'production_database_switch': False, 'production_cdb_modified': False,
             'source_release_manifest_sha256': self.release, 'source_cdb_sha256': self.cdb}
        key = 'previous-secondary.json' if previous else 'current-secondary.json'
        (self.root / key).write_text(json.dumps(p))

    def test_authentic_offline_not_mislabeled_as_current(self):
        r=health.inspect(self.root)
        self.assertEqual(r['status'], 'PINNED_SECONDARY_VERIFIED_FRESHNESS_UNCHECKED')
        self.assertIsNone(r['data_parity_to_current_primary'])
        self.assertFalse(r['serving_cutover_authorized'])

    def test_live_match_confirms_snapshot_version_only(self):
        with patch.object(health,'live_release_manifest_sha256',return_value=self.release):
            self.assertTrue(health.inspect(self.root,verify_live=True)['data_parity_to_current_primary'])

    def test_live_moved_blocks_current_status(self):
        with patch.object(health,'live_release_manifest_sha256',return_value='f'*64):
            self.assertEqual(health.inspect(self.root,verify_live=True)['status'], 'SECONDARY_LAGGING_BEHIND_PRIMARY')

    def test_artifact_tamper_blocks(self):
        path=self.root/'first.sqlite'
        with path.open('ab') as f:f.write(b'bad')
        with self.assertRaisesRegex(ValueError,'artifact bytes'):health.inspect(self.root)

    def test_receipt_tamper_blocks(self):
        p=self.root/'first.sqlite.parity.json'; data=json.loads(p.read_text())
        data['counts']['cdb_stat_cells_missing_effective_dil']=1
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'failures'):health.inspect(self.root)

    def test_training_or_production_claim_blocks(self):
        p=self.root/'first.sqlite.import.json'; data=json.loads(p.read_text())
        data['production_promoted']=True
        p.write_text(json.dumps(data))
        with self.assertRaises(ValueError):health.inspect(self.root)

    def test_absent_receipt_blocks(self):
        (self.root/'first.sqlite.parity.json').unlink()
        with self.assertRaises(ValueError):health.inspect(self.root)

    def test_wrong_counts_blocks(self):
        p=self.root/'first.sqlite.import.json'; data=json.loads(p.read_text())
        data['canonical_matches_after']=2
        p.write_text(json.dumps(data))
        with self.assertRaises(ValueError):health.inspect(self.root)

    def test_guarded_rollback_never_changes_primary(self):
        self.create('older.sqlite')
        self.pointer('older.sqlite', previous=True)
        with self.assertRaisesRegex(ValueError,'compare-and-swap'):
            health.rollback(self.root, 'wrong.sqlite')
        good=health.rollback(self.root,'first.sqlite')
        self.assertEqual(good['status'],'SECONDARY_POINTER_ROLLED_BACK')
        self.assertEqual(json.loads((self.root/'current-secondary.json').read_text())['filename'],'older.sqlite')
        self.assertEqual(json.loads((self.root/'previous-secondary.json').read_text())['filename'],'first.sqlite')

    def test_previous_missing_rejects_rollback(self):
        with self.assertRaises(ValueError):health.rollback(self.root,'first.sqlite')

    def test_filename_traversal_rejected(self):
        self.pointer('../first.sqlite')
        with self.assertRaisesRegex(ValueError,'filename'):health.inspect(self.root)

    def test_live_double_metadata_stability(self):
        class Obj:
            def __init__(self,d):self.returncode=0;self.stdout=json.dumps({'tag_name':'tbt-data-v1','assets':
                [{'name':'history_manifest.json','digest':'sha256:'+d,'id':1}]+[
                    {'name':f'history-{year}.parquet','digest':'sha256:'+'b'*64,'id':year} for year in range(1949,2027)]})
        with patch.object(health.subprocess,'run',side_effect=[Obj('a'*64),Obj('c'*64)]):
            with self.assertRaisesRegex(ValueError,'changed'):health.live_release_manifest_sha256()

if __name__=='__main__':unittest.main()