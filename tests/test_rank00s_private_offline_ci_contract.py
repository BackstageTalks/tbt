"""Static safety contract for private rank00s Python-only public-runner bridge."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/rank00s-private-offline-ci.yml"
SOURCE_SHA = "8dc768b1f8af3e82790c9840aaf0a6bdadd0b652"


class ReadOnlyBridgeContract(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_no_cron_no_push_no_release_writer(self):
        text = self.text
        self.assertNotIn("  push:", text)
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
        self.assertIn("a20d4db858dad65104c87dc707fdf6abeaef036f", text)
        self.assertIn("23ed65dc526d300fd24994d01640d06f84f12ba5", text)
        self.assertNotIn("checkout@v4\n        with:\n          repository: BackstageTalks/tbt-data", text)

    def test_unsafe_fork_pr_excluded(self):
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", self.text)

    def test_no_private_output_artifact_or_test_dump(self):
        text = self.text
        self.assertNotIn("upload-artifact@", text)
        self.assertNotIn("cat /tmp/private-offline-test.log", text)
        self.assertIn("GH_TOKEN: ''", text)
        self.assertIn(">/tmp/private-offline-test.log 2>&1", text)
        self.assertIn("PINNED_RANK00S_12_SYNTHETIC_TESTS_PASSED", text)


if __name__ == "__main__":
    unittest.main()
