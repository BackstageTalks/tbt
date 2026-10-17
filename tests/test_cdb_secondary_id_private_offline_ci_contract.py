"""Static security contract for SHA-pinned private CDB identity test bridge."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/cdb-secondary-id-private-offline-ci.yml"
SOURCE_SHA = "24a947cc7434dff90d210bae2b938f23a0900ba3"
SHAS = {
    "scripts/reconcile_l2_cdb_identity.py": "cfa3fe13dc72543abf6c200d31ef9c1bbefd792e",
    "scripts/l2_metadata_candidates.py": "0b01a685a63c68f073ebd644fbf573b079153fc7",
    "scripts/secondary_id_map.py": "377282f2d06ffb88e1b14623c97f8019e054bfeb",
    "tests/test_reconcile_l2_cdb_identity.py": "71c4a7b2060c64cb12fe37767b6eabc577a9b173",
    "tests/test_secondary_id_map.py": "60afa4bd47e2f761dd55d9cad2756f86e4099289",
}


class ReadOnlySecondaryIDContract(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_only_trusted_main_and_manual_main_trigger(self):
        t = self.text
        self.assertIn("  push:\n    branches: [main]", t)
        self.assertIn("  workflow_dispatch:", t)
        self.assertIn("github.ref == 'refs/heads/main'", t)
        self.assertNotIn("  pull_request:", t)
        self.assertNotIn("  schedule:", t)
        self.assertNotIn("workflow_dispatch:\n    inputs:", t)

    def test_read_only_and_private_token_only_during_fetch(self):
        t = self.text
        self.assertIn("permissions:\n  contents: read", t)
        self.assertIn("persist-credentials: false", t)
        self.assertIn("          GH_TOKEN: ${{ secrets.TBT_DATA_GH_TOKEN }}", t)
        self.assertNotIn("\n      GH_TOKEN: ${{ secrets.TBT_DATA_GH_TOKEN }}", t)
        self.assertIn("          GH_TOKEN: ''", t)
        self.assertIn("          GITHUB_TOKEN: ''", t)
        self.assertNotIn("upload-artifact@", t)
        self.assertNotIn("actions/cache@", t)

    def test_only_five_exact_private_sources_at_fixed_sha(self):
        t = self.text
        self.assertIn("SOURCE_COMMIT: " + SOURCE_SHA, t)
        self.assertEqual(t.count('gh api "repos/$PRIVATE_REPO/contents/'), 5)
        for path, blob in SHAS.items():
            self.assertIn("contents/" + path + "?ref=$SOURCE_COMMIT", t)
            self.assertIn('git hash-object private/' + path, t)
            self.assertIn(blob, t)
        self.assertNotIn("repository: BackstageTalks/tbt-data", t)

    def test_both_suites_and_no_private_logging(self):
        t = self.text
        self.assertIn("'test_secondary_id_map.py'", t)
        self.assertIn("'test_reconcile_l2_cdb_identity.py'", t)
        self.assertIn("CDB_SECONDARY_ID_TWO_PRIVATE_SUITES_PASSED", t)
        self.assertIn(">/tmp/cdb-secondary-unit.log 2>&1", t)
        self.assertIn(">/tmp/cdb-secondary-integration.log 2>&1", t)
        self.assertNotIn("cat /tmp/cdb-secondary", t)
        self.assertNotIn("tee /tmp/cdb-secondary", t)


if __name__ == "__main__":
    unittest.main()
