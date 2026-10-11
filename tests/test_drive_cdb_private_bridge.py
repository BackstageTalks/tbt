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
            code.write_text('v1'); (target / 'audit.sqlite.gz').write_bytes(b'tampered')
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
            (p / 'files.json').write_text('[{"id":"one"}]')
            (p / 'drive-inventory.json').write_text('[{"id":"one"}]')
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

    def test_empty_candidate_fields_survives_private_tar_report_roundtrip(self):
        # Prior live audit #38151013504 verified CDB read-only but failed
        # to publish because gh release upload rejects a zero-byte asset.
        # One nonempty archive must preserve the original zero-byte file.
        import subprocess
        with TemporaryDirectory() as d:
            p = Path(d)
            source = p / 'private-output'
            source.mkdir()
            (source / 'candidate-fields.jsonl').write_bytes(b'')
            (source / 'report.json').write_text('{"cdb_writes":0}')
            expected = {}
            import hashlib
            for name in ('candidate-fields.jsonl', 'report.json'):
                expected[name] = hashlib.sha256((source / name).read_bytes()).hexdigest()
            (source / 'SHA256SUMS').write_text(
                ''.join(f'{digest}  {name}\n' for name, digest in expected.items()))
            bundle = p / 'drive-cdb-audit-bundle.tar.gz'
            subprocess.run(['tar', '-czf', str(bundle), '-C', str(source), '.'], check=True)
            self.assertGreater(bundle.stat().st_size, 0)
            readback = p / 'readback'
            readback.mkdir()
            subprocess.run(['tar', '-xzf', str(bundle), '-C', str(readback)], check=True)
            subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=readback,
                           check=True, capture_output=True)
            self.assertEqual((readback / 'candidate-fields.jsonl').stat().st_size, 0)
            self.assertEqual((readback / 'report.json').read_bytes(),
                             (source / 'report.json').read_bytes())

    def test_missing_cache_is_not_false_success(self):
        with TemporaryDirectory() as d:
            p = Path(d); code = p / 'parser.py'; code.write_text('v1')
            self.assertFalse(restore_checkpoint(p, code, FOLDER, p / 'output.sqlite'))
            self.assertFalse((p / 'output.sqlite').exists())


    def test_checkpoint_is_compressed_checks_raw_bytes_and_restores_atomically(self):
        import hashlib
        with TemporaryDirectory() as d:
            p = Path(d)
            cache = p / 'audit.sqlite'
            cache.write_bytes(b'sqlite-test-payload' * 15000)
            code = p / 'audit.py'
            code.write_text('one')
            out = p / 'checkpoint'
            write_checkpoint(cache, code, FOLDER, out)
            packed = out / 'audit.sqlite.gz'
            self.assertTrue(packed.is_file())
            self.assertFalse((out / 'audit.sqlite').exists())
            self.assertLess(packed.stat().st_size, cache.stat().st_size)
            manifest = json.loads((out / 'checkpoint.json').read_text())
            self.assertEqual(manifest['schema'], 2)
            self.assertEqual(manifest['checkpoint_file'], 'audit.sqlite.gz')
            self.assertEqual(manifest['uncompressed_checkpoint_bytes'], cache.stat().st_size)
            self.assertEqual(manifest['uncompressed_checkpoint_sha256'],
                             hashlib.sha256(cache.read_bytes()).hexdigest())
            recovered = p / 'recovered.sqlite'
            self.assertTrue(restore_checkpoint(out, code, FOLDER, recovered))
            self.assertEqual(cache.read_bytes(), recovered.read_bytes())
            # An otherwise correctly checksummed gzip must not restore
            # if its uncompressed content differs from the pinned manifest.
            manifest['uncompressed_checkpoint_sha256'] = '0' * 64
            (out / 'checkpoint.json').write_text(json.dumps(manifest))
            recovered.write_bytes(b'preserve-existing')
            self.assertFalse(restore_checkpoint(out, code, FOLDER, recovered))
            self.assertEqual(recovered.read_bytes(), b'preserve-existing')

    def test_legacy_v1_checkpoint_remains_readable(self):
        import hashlib
        with TemporaryDirectory() as d:
            p = Path(d)
            code = p / 'audit.py'
            code.write_text('old')
            source = p / 'cache'
            source.mkdir()
            blob = source / 'audit.sqlite'
            blob.write_bytes(b'legacy-cache')
            sha = lambda b: hashlib.sha256(b).hexdigest()
            (source / 'checkpoint.json').write_text(json.dumps({
                'schema': 1,
                'folder_id': FOLDER,
                'source_audit_code_sha256': sha(code.read_bytes()),
                'checkpoint_sha256': sha(blob.read_bytes()),
                'checkpoint_bytes': blob.stat().st_size,
            }))
            dest = p / 'legacy-restored.sqlite'
            self.assertTrue(restore_checkpoint(source, code, FOLDER, dest))
            self.assertEqual(dest.read_bytes(), blob.read_bytes())



if __name__ == '__main__':
    unittest.main()
