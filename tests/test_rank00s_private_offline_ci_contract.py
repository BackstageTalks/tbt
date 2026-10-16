"""Static safety contract for private rank00s Python-only public-runner bridge."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/rank00s-private-offline-ci.yml"
SOURCE_SHA = "c9a1b4df15bc87c955418d86467368339f47c8c7"


class ReadOnlyBridgeContract(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_no_cron_no_push_no_release_writer(self):
        text = self.text
        self.assertNotIn("  push:", text)
        self.assertNotIn("  pull_request:", text)
        self.assertNotIn("  schedule:", text)
        self.assertNotIn("releases/tags/", text)
        self.assertNotIn("git/refs", text)
        self.assertNotIn(" gh release ", text)
        self.assertNotIn("workflow_dispatch:\n    inputs:", text)
        self.assertIn("  contents: read", text)
        self.assertIn("  workflow_dispatch:", text)

    def test_private_ref_is_immutable_and_only_two_python_files(self):
        text = self.text
        self.assertIn("SOURCE_COMMIT: " + SOURCE_SHA, text)
        self.assertIn("scripts/preflight_rank00s_cdb.py?ref=$SOURCE_COMMIT", text)
        self.assertIn("tests/test_preflight_rank00s_cdb.py?ref=$SOURCE_COMMIT", text)
        self.assertIn("2553a906fcd4ab74dafcd9995888d71da92e8233", text)
        self.assertIn("508e54a39d0848c4b247d4d53503b66019c885d0", text)
        self.assertNotIn("checkout@v4\n        with:\n          repository: BackstageTalks/tbt-data", text)

    def test_manual_run_on_protected_main_only_and_secret_step_scoped(self):
        self.assertIn("github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'", self.text)
        self.assertNotIn("github.event.pull_request", self.text)
        self.assertNotIn("  pull_request:", self.text)
        self.assertIn("          GH_TOKEN: ${{ secrets.TBT_DATA_GH_TOKEN }}", self.text)
        self.assertNotIn("\n      GH_TOKEN: ${{ secrets.TBT_DATA_GH_TOKEN }}", self.text)

    def test_no_private_output_artifact_or_test_dump(self):
        text = self.text
        self.assertNotIn("upload-artifact@", text)
        self.assertNotIn("cat /tmp/private-offline-test.log", text)
        self.assertIn("GH_TOKEN: ''", text)
        self.assertIn(">/tmp/private-offline-test.log 2>&1", text)
        self.assertIn("PINNED_RANK00S_21_SYNTHETIC_TESTS_PASSED", text)


if __name__ == "__main__":
    unittest.main()
