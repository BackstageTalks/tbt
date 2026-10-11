import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from scripts.audit_private_drive_report_summary import summarize

YEAR = 'a' * 64

def create_bundle(where, candidate_lines=(), report_overrides=None, tamper_digest=False,
                  file_rows=None):
    files = {
        'report.json': json.dumps({
            'inventory_complete': True, 'cdb_writes': 0, 'approved_fields': 0,
            'canonical_partition_sha256': {'history-2026.parquet': YEAR},
            'scope_folder_id': '17UChTTWLpC-7tZIbvTXKA4_2eqooV44A',
            'inventory_files': 2, 'file_statuses': {'CACHED': 2},
            'comparison': {'candidate_missing_fields': len(candidate_lines)},
            **(report_overrides or {})
        }).encode(),
        'candidate-fields.jsonl': b''.join(json.dumps(x).encode() + b'\n' for x in candidate_lines),
        'files.json': json.dumps(file_rows if file_rows is not None else [{},{}]).encode(),
        'run-evidence.txt': b'audit_outcome=success\n'
    }
    files['SHA256SUMS'] = ''.join(f'{hashlib.sha256(v).hexdigest()}  {k}\n'
                                 for k, v in files.items()).encode()
    if tamper_digest:
        files['report.json'] += b'\n'
    blob = io.BytesIO()
    with tarfile.open(fileobj=blob, mode='w:gz') as tar:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            tar.addfile(member, io.BytesIO(content))
    dest = where / 'audit.tar.gz'
    dest.write_bytes(blob.getvalue())
    return dest, hashlib.sha256(blob.getvalue()).hexdigest()

class SummaryTests(unittest.TestCase):
    def test_empty_candidate_is_true_zero(self):
        with tempfile.TemporaryDirectory() as d:
            path, digest = create_bundle(Path(d))
            found = summarize(path, digest, YEAR)
            self.assertEqual(found['candidate_missing_fields'], 0)
            self.assertEqual(found['statuses'], {'CACHED': 2})

    def test_research_candidates_not_import_ready(self):
        with tempfile.TemporaryDirectory() as d:
            path, digest = create_bundle(Path(d), [
                {'match_id': 'private', 'field': 'p1_aces', 'value': 3,
                 'evidence': [{'identity_kind': 'sackmann_research'}], 'import_ready': False}
            ])
            found = summarize(path, digest, YEAR)
            self.assertEqual(found['candidate_evidence_identity_kinds'], {'sackmann_research': 1})
            self.assertEqual(found['approved_to_import'], 0)

    def test_unsupported_format_census_never_leaks_filename(self):
        with tempfile.TemporaryDirectory() as d:
            names = [
                {'name':'PERSONAL-PRIVATE-CASE.tar.gz', 'status':'NEEDS_FORMAT_ADAPTER'},
                {'name':'another-private-source.json', 'status':'NEEDS_FORMAT_ADAPTER'}
            ]
            path, digest = create_bundle(Path(d), file_rows=names,
                 report_overrides={'file_statuses': {'NEEDS_FORMAT_ADAPTER':2}})
            found = summarize(path, digest, YEAR)
            self.assertEqual(found['unprocessed_extensions_by_status'],
                {'NEEDS_FORMAT_ADAPTER': {'.tar.gz':1, '.json':1}})
            self.assertNotIn('PERSONAL', json.dumps(found))
            self.assertNotIn('another-private', json.dumps(found))

    def test_bad_bundle_sha(self):
        with tempfile.TemporaryDirectory() as d:
            path, _ = create_bundle(Path(d))
            with self.assertRaisesRegex(ValueError, 'bundle SHA'):
                summarize(path, '0' * 64, YEAR)

    def test_inner_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            path, digest = create_bundle(Path(d), tamper_digest=True)
            with self.assertRaisesRegex(ValueError, 'Member SHA'):
                summarize(path, digest, YEAR)

    def test_stale_cdb_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            path, digest = create_bundle(Path(d))
            with self.assertRaisesRegex(ValueError, 'Current CDB'):
                summarize(path, digest, 'b' * 64)

    def test_import_ready_proposal_fails(self):
        with tempfile.TemporaryDirectory() as d:
            path, digest = create_bundle(Path(d), [
                {'match_id': 'private', 'field': 'p1_aces', 'value': 3, 'import_ready': True}
            ])
            with self.assertRaisesRegex(ValueError, 'import-ready'):
                summarize(path, digest, YEAR)

    def test_wrong_inventory_count(self):
        with tempfile.TemporaryDirectory() as d:
            path, digest = create_bundle(Path(d), report_overrides={'inventory_files': 3})
            with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
                summarize(path, digest, YEAR)

if __name__ == '__main__':
    unittest.main()
