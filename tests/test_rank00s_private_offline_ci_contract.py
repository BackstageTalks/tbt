"""Static safety contract for private rank00s Python-only public-runner bridge."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/rank00s-private-offline-ci.yml"
SOURCE_SHA = "02f98b3404b974e48899ce88e48586d270821bfe"


class ReadOnlyBridgeContract(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_main_only_path_restricted_push_without_writer(self):
        text = self.text
        self.assertIn("  push:\\n    branches: [main]\\n    paths:\\n      - '.github/workflows/rank00s-private-offline-ci.yml'", text)
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
        self.assertIn("020198a54d5e44ec455457e1056b5c7442cb68fe", text)
        self.assertIn("a9219fdc6ec72ff4517a2b8a48b8ba6afe2748be", text)
        self.assertNotIn("checkout@v4\n        with:\n          repository: BackstageTalks/tbt-data", text)

    def test_protected_main_only_and_secret_step_scoped(self):
        self.assertIn("github.event_name == 'workflow_dispatch' || github.event_name == 'push'", self.text)
        self.assertIn("github.ref == 'refs/heads/main'", self.text)
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
        self.assertIn("PINNED_RANK00S_24_SYNTHETIC_TESTS_PASSED", text)


if __name__ == "__main__":
    unittest.main()
