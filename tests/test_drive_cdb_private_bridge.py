import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from drive_cdb_private_bridge import validate, write_checkpoint, restore_checkpoint

FOLDER = '17UChTTWLpC-7tZIbvTXKA4_2eqooV44A'


class PrivateBridgeTest(unittest.TestCase):
    def test_checkpoint_bound_to_drive_root_and_code_and_bytes(self):
        with TemporaryDirectory() as d:
            p = Path(d)
            cache = p / 'one.sqlite'; cache.write_bytes(b'sqlite-bytes')
            code = p / 'parser.py'; code.write_text('v1')
            target = p / 'checkpoint'
            write_checkpoint(cache, code, FOLDER, target)
            recovered = p / 'recovered.sqlite'
            self.assertTrue(restore_checkpoint(target, code, FOLDER, recovered))
            self.assertEqual(cache.read_bytes(), recovered.read_bytes())
            self.assertFalse(restore_checkpoint(target, code, 'other-folder-abc', p / 'bad.sqlite'))
            code.write_text('v2')
            self.assertFalse(restore_checkpoint(target, code, FOLDER, p / 'bad2.sqlite'))
            code.write_text('v1'); (target / 'audit.sqlite').write_bytes(b'tampered')
            self.assertFalse(restore_checkpoint(target, code, FOLDER, p / 'bad3.sqlite'))

    def test_report_blocks_missing_or_unsafe_gate(self):
        with TemporaryDirectory() as d:
            p = Path(d)
            report = {'scope_folder_id': FOLDER, 'inventory_complete': True,
                      'inventory_files': 1, 'canonical_rows': 994101,
                      'approved_fields': 0, 'cdb_writes': 0,
                      'all_data_importability_assessed': False,
                      'canonical_partition_sha256': {
                          f'history-{year}.parquet': 'a' * 64 for year in range(1950, 2028)
                      }, 'comparison': {'candidate_missing_fields': 0}}
            (p / 'report.json').write_text(json.dumps(report))
            (p / 'files.json').write_text('[]')
            (p / 'drive-inventory.json').write_text('[]')
            (p / 'candidate-fields.jsonl').write_text('')
            self.assertEqual(validate(p, FOLDER)['canonical_rows'], 994101)
            with self.assertRaises(ValueError): validate(p, 'different-root-id')
            report['cdb_writes'] = 1
            (p / 'report.json').write_text(json.dumps(report))
            with self.assertRaises(ValueError): validate(p, FOLDER)
            report['cdb_writes'] = 0
            (p / 'report.json').write_text(json.dumps(report))
            (p / 'candidate-fields.jsonl').write_text(json.dumps({'import_ready': True}) + '\n')
            with self.assertRaises(ValueError): validate(p, FOLDER)

    def test_missing_cache_is_not_false_success(self):
        with TemporaryDirectory() as d:
            p = Path(d); code = p / 'parser.py'; code.write_text('v1')
            self.assertFalse(restore_checkpoint(p, code, FOLDER, p / 'output.sqlite'))
            self.assertFalse((p / 'output.sqlite').exists())


if __name__ == '__main__':
    unittest.main()
