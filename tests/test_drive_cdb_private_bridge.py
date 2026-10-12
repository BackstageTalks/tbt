import json
import hashlib
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from drive_cdb_private_bridge import (validate, write_checkpoint, restore_checkpoint,
                                      verify_priority_reader_migration)

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

    def test_compressed_real_sqlite_roundtrip_preserves_rows(self):
        with TemporaryDirectory() as d:
            p = Path(d)
            db = p / 'cache.sqlite'
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE evidence(id INTEGER PRIMARY KEY, value TEXT)')
                conn.executemany('INSERT INTO evidence(value) VALUES (?)',
                                 [('important source evidence ' + str(i),) for i in range(1000)])
            code = p / 'reader.py'; code.write_text('v1')
            checkpoint = p / 'checkpoint'
            write_checkpoint(db, code, FOLDER, checkpoint)
            metadata = json.loads((checkpoint / 'checkpoint.json').read_text())
            self.assertEqual(metadata['schema'], 2)
            self.assertEqual(metadata['encoding'], 'gzip')
            self.assertEqual(metadata['uncompressed_sha256'], hashlib.sha256(db.read_bytes()).hexdigest())
            self.assertLess((checkpoint / 'audit.sqlite.gz').stat().st_size, db.stat().st_size)
            self.assertFalse((checkpoint / 'audit.sqlite').exists())
            restored = p / 'restored.sqlite'
            self.assertTrue(restore_checkpoint(checkpoint, code, FOLDER, restored))
            self.assertEqual(restored.read_bytes(), db.read_bytes())
            with sqlite3.connect(restored) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM evidence').fetchone()[0], 1000)

    def test_legacy_raw_checkpoint_is_backward_compatible(self):
        with TemporaryDirectory() as d:
            p = Path(d)
            code = p / 'parser.py'; code.write_text('unchanged-pinned-reader')
            folder = p / 'previous'; folder.mkdir()
            old = folder / 'audit.sqlite'; old.write_bytes(b'previous-private-cache')
            manifest = {
                'schema': 1, 'folder_id': FOLDER,
                'source_audit_code_sha256': hashlib.sha256(code.read_bytes()).hexdigest(),
                'checkpoint_sha256': hashlib.sha256(old.read_bytes()).hexdigest(),
                'checkpoint_bytes': old.stat().st_size,
            }
            (folder / 'checkpoint.json').write_text(json.dumps(manifest))
            dest = p / 'restored.sqlite'
            self.assertTrue(restore_checkpoint(folder, code, FOLDER, dest))
            self.assertEqual(dest.read_bytes(), old.read_bytes())
            manifest['checkpoint_sha256'] = 'a'*64
            (folder / 'checkpoint.json').write_text(json.dumps(manifest))
            self.assertFalse(restore_checkpoint(folder, code, FOLDER, dest))
            self.assertEqual(dest.read_bytes(), old.read_bytes())

    def test_bad_gzip_and_wrong_raw_digest_fail_without_wiping_existing_cache(self):
        with TemporaryDirectory() as d:
            p = Path(d); code = p / 'parser.py'; code.write_text('v1')
            source = p / 'source.sqlite'; source.write_bytes(b'important old cache'*2000)
            folder = p / 'checkpoint'
            write_checkpoint(source, code, FOLDER, folder)
            dest = p / 'restored.sqlite'; dest.write_bytes(b'KEEP')
            metadata = json.loads((folder / 'checkpoint.json').read_text())
            metadata['uncompressed_sha256'] = 'a'*64
            (folder / 'checkpoint.json').write_text(json.dumps(metadata))
            self.assertFalse(restore_checkpoint(folder, code, FOLDER, dest))
            self.assertEqual(dest.read_bytes(), b'KEEP')
            self.assertFalse((p / 'restored.sqlite.pending').exists())
            write_checkpoint(source, code, FOLDER, folder)
            (folder / 'audit.sqlite.gz').write_bytes(b'corrupt gzip bytes')
            self.assertFalse(restore_checkpoint(folder, code, FOLDER, dest))
            self.assertEqual(dest.read_bytes(), b'KEEP')

    def test_cache_bounds_fail_closed_before_writing_checkpoint(self):
        from unittest.mock import patch
        with TemporaryDirectory() as d:
            p = Path(d)
            code = p / 'parser.py'; code.write_text('v1')
            source = p / 'source.sqlite'; source.write_bytes(b'x'*128)
            with patch('drive_cdb_private_bridge.MAX_RAW_CHECKPOINT_BYTES', 100):
                with self.assertRaises(ValueError):
                    write_checkpoint(source, code, FOLDER, p / 'too-big')
            with patch('drive_cdb_private_bridge.MAX_COMPRESSED_CHECKPOINT_BYTES', 5):
                with self.assertRaises(ValueError):
                    write_checkpoint(source, code, FOLDER, p / 'not-uploaded')
            self.assertFalse((p / 'not-uploaded' / 'checkpoint.json').exists())
            self.assertFalse((p / 'not-uploaded' / 'audit.sqlite.gz.pending').exists())

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


    def test_priority_reader_migration_exact_code_contract(self):
        # Use minimal synthetic scripts matching the only three allowed edits.
        with TemporaryDirectory() as d:
            p = Path(d)
            legacy = p / 'original.py'
            current = p / 'priority.py'
            original = (
                'import re\n'
                'from pathlib import Path\n'
                'def records(stream, suffix):\n'
                '    return stream\n'
                'def main():\n'
                '    ap = argparse.ArgumentParser()\n'
                '    args = ap.parse_args()\n'
                '    for item in inventory:\n'
                '        print(item)\n'
            )
            legacy.write_text(original, encoding='utf-8')
            priority = original.replace(
                'def records(stream, suffix):\n',
                'def audit_source_priority(item):\n'
                '    return (0, item)\n\n'
                'def records(stream, suffix):\n', 1
            )
            priority = priority.replace(
                '    args = ap.parse_args()\n',
                "    ap.add_argument('--prioritize-historical-stats', action='store_true',\n"
                "                    help='Opt in to historical match-stat sample ordering; default preserves existing checkpoint order')\n"
                '    args = ap.parse_args()\n', 1
            )
            priority = priority.replace(
                '    for item in inventory:',
                '    # Keep default scanner behavior identical for pinned production checkpoints.\n'
                '    # A new priority policy needs an explicitly reviewed cache/code migration.\n'
                '    ordered = sorted(inventory, key=audit_source_priority) if args.prioritize_historical_stats else inventory\n'
                '    for item in ordered:', 1
            )
            current.write_text(priority, encoding='utf-8')
            verify_priority_reader_migration(legacy, current)
            current.write_text(priority.replace('return stream', 'return None'), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'semantics changed'):
                verify_priority_reader_migration(legacy, current)
            current.write_text(priority.replace(
                '    for item in ordered:', '    for item in unknown_source:'), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'loop contract'):
                verify_priority_reader_migration(legacy, current)

    def test_actual_workflow_uses_pinned_new_reader_and_legacy_checkpoint(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    '.github/workflows/blinq-private-drive-cdb-audit-bridge.yml').read_text()
        self.assertIn('SOURCE_REF: 10806400e536195890600c4256303697912ab95f', workflow)
        self.assertIn('LEGACY_SOURCE_REF: cf96b6085f93696eb7c319e9109a2040a04cfc4e', workflow)
        self.assertIn('ref: ${{ env.SOURCE_REF }}\n          fetch-depth: 1\n          path: private', workflow)
        self.assertIn('git -C private rev-parse --verify HEAD', workflow)
        self.assertIn('test "$actual" = "$SOURCE_REF"', workflow)
        self.assertIn('verify-priority-reader --legacy-code work/legacy-drive-cdb-audit.py', workflow)
        self.assertIn('--code-file work/legacy-drive-cdb-audit.py --source work/cache-input', workflow)
        self.assertIn('VERIFIED_LEGACY_CHECKPOINT_MIGRATED_TO_PRIORITY_READER', workflow)
        self.assertIn('VERIFIED_PRIVATE_SQLITE_CACHE_INTEGRITY', workflow)
        self.assertIn('--prioritize-historical-stats --folder-id "$DRIVE_ROOT"', workflow)
        self.assertIn('source_sampling=historical_stats_priority', workflow)
        self.assertIn("if: github.event_name == 'workflow_dispatch'", workflow)
        self.assertNotIn('schedule:', workflow)

    def test_rapid_external_dispatch_is_budget_bounded_and_null_errors_redacted(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    '.github/workflows/blinq-private-drive-cdb-audit-bridge.yml').read_text()
        self.assertIn('  scan_budget:', workflow)
        self.assertIn('age < 5400', workflow)
        self.assertIn('DRIVE_AUDIT_COOLDOWN_SKIP_90_MINUTES', workflow)
        self.assertIn("needs.scan_budget.outputs.proceed == 'true'", workflow)
        self.assertIn('needs: [safety-tests, scan_budget]', workflow)
        self.assertIn('force_scan:', workflow)
        self.assertIn('DRIVE_AUDIT_EXPLICIT_OVERRIDE', workflow)
        self.assertIn('DRIVE_AUDIT_BUDGET_BLOCKED_UNVERIFIED_CHECKPOINT', workflow)
        self.assertIn('PRIVATE_CURRENT_NULL_RECHECK_BLOCKED_', workflow)
        self.assertIn('UNKNOWN_PRIVATE', workflow)
        self.assertNotIn('print(text)', workflow)
        self.assertNotIn('schedule:', workflow)
        # The scanner retains its fail-closed provenance and zero-write path.
        self.assertIn('PRIVATE_CURRENT_NULL_RECHECK_PASS_NO_WRITES', workflow)
        self.assertIn('--prioritize-historical-stats', workflow)

    def test_private_drive_checkout_ref_remains_immutable(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    '.github/workflows/blinq-private-drive-cdb-audit-bridge.yml').read_text()
        self.assertIn('SOURCE_REF: 10806400e536195890600c4256303697912ab95f', workflow)
        pinned = next(line.split(': ', 1)[1].strip() for line in workflow.splitlines()
                      if line.strip().startswith('SOURCE_REF: '))
        self.assertEqual(len(pinned), 40)
        self.assertTrue(all(ch in '0123456789abcdef' for ch in pinned))
        self.assertIn('ref: ${{ env.SOURCE_REF }}\n          fetch-depth: 1\n          path: private', workflow)
        self.assertIn('git -C private rev-parse --verify HEAD', workflow)
        self.assertIn('test "$actual" = "$SOURCE_REF"', workflow)
        self.assertIn('PINNED_PRIVATE_SOURCE_SHA_VERIFIED', workflow)
        self.assertNotIn('ref: main\n          fetch-depth: 64', workflow)
        self.assertNotIn('git -C private checkout --detach "$SOURCE_REF"', workflow)
        self.assertIn('--prioritize-historical-stats', workflow)


if __name__ == '__main__':
    unittest.main()
