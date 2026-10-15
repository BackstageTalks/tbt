import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'build_uploaded_cdb_source_layer.py'
spec = importlib.util.spec_from_file_location('build_uploaded_cdb_source_layer', SCRIPT)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


class SourceLayerContractTest(unittest.TestCase):
    def test_deterministic_gzip_and_stable_source_hash(self):
        content = b'private-source-evidence\n'
        first = subject.gzip_bytes(content)
        self.assertEqual(first, subject.gzip_bytes(content))
        import gzip
        self.assertEqual(gzip.decompress(first), content)
        self.assertEqual(subject.digest(b'hello'), '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824')

    def test_fail_closed_missing_or_wrong_bundle(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'invalid.zip'
            p.write_bytes(b'untrusted')
            with self.assertRaisesRegex(ValueError, 'Untrusted raw archive SHA256'):
                subject.verified_source(p)

    def test_contract_never_promotes_raw_id_to_canonical(self):
        code=SCRIPT.read_text()
        self.assertIn("'canonical_match_id': None",code)
        self.assertIn("'import_ready': False, 'write_authorized': False",code)
        self.assertIn("'quote_capture_utc': None",code)
        self.assertIn("'prematch_feature_allowed': False",code)
        self.assertNotIn('upload_bundle(',code)


if __name__ == '__main__':
    unittest.main()