"""Static security contract: public DIL runner downloads only immutable private files.

No proprietary content is committed to the public repository or logged by CI.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/dil-v2-private-offline-ci.yml"
SOURCE_SHA = "1ebe0365190bed1b8a351670578f5dfb4d1d8649"


class PublicDILV2BridgeContract(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_main_only_no_pull_request_or_scheduling(self):
        t = self.workflow
        self.assertIn("  push:\n    branches: [main]", t)
        self.assertIn("  workflow_dispatch:", t)
        self.assertIn("github.ref == 'refs/heads/main'", t)
        self.assertNotIn("  pull_request:", t)
        self.assertNotIn("  pull_request_target:", t)
        self.assertNotIn("  schedule:", t)

    def test_readonly_privilege_and_step_scoped_token(self):
        t = self.workflow
        self.assertIn("permissions:\n  contents: read", t)
        self.assertIn("persist-credentials: false", t)
        secret = r"GH_TOKEN: ${{ secrets.TBT_DATA_GH_TOKEN }}"
        self.assertEqual(t.count(secret), 1)
        self.assertIn("          GH_TOKEN: ''", t)
        self.assertIn("          GITHUB_TOKEN: ''", t)
        self.assertNotIn("upload-artifact@", t)
        self.assertNotIn("actions/cache@", t)
        self.assertNotIn("cat /tmp/dil-v2", t)
        self.assertNotIn("tee /tmp/dil-v2", t)
        self.assertIn("if: always()", t)
        self.assertIn("rm -rf private", t)

    def test_pinned_private_ref_files_and_blob_hashes(self):
        t = self.workflow
        self.assertIn("SOURCE_COMMIT: " + SOURCE_SHA, t)
        self.assertIn("repos/$PRIVATE_REPO/contents/$source_path?ref=$SOURCE_COMMIT", t)
        self.assertIn("git hash-object", t)
        block = t.split("done <<'SHA_PINNED_FILES'\n", 1)[1].split("\n          SHA_PINNED_FILES", 1)[0]
        lines = [line for line in block.splitlines() if line]
        self.assertEqual(len(lines), 21)
        parsed = [line.strip().split("|") for line in lines]
        self.assertTrue(all(len(p) == 2 for p in parsed))
        paths = [p for p, _ in parsed]
        self.assertEqual(len(set(paths)), 21)
        self.assertEqual(sum(p.startswith("til_v2/") for p in paths), 14)
        self.assertEqual(sum(p.startswith("tests/") for p in paths), 7)
        for p, digest in parsed:
            self.assertTrue(re.fullmatch(r"[a-zA-Z0-9_/.-]+", p), p)
            self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", digest), p)
        self.assertNotIn("gh release download", t)
        self.assertNotIn("download_private_drive", t)
        self.assertNotIn("git push", t)

    def test_synthetic_duckdb_no_private_output(self):
        t = self.workflow
        self.assertIn("'duckdb>=1.1,<2'", t)
        self.assertIn("test_til_v2*.py", t)
        self.assertIn("test_dil_core.py", t)
        self.assertIn("DIL_V2_ALL_PRIVATE_SYNTHETIC_SUITES_PASSED", t)
        self.assertIn(">/tmp/dil-v2-contract.log 2>&1", t)
        self.assertIn(">/tmp/dil-v2-core.log 2>&1", t)
        self.assertIn("DIL_V2_21_PRIVATE_BLOB_HASHES_VERIFIED", t)


if __name__ == "__main__":
    unittest.main()
