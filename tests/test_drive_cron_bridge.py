"""Static regression gate for the existing external Drive/CDB cron URL.

No GitHub credentials or Drive mutations are needed for these tests.
"""
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / ".github/workflows/blinq-private-drive-cdb-audit-bridge.yml"
CONTENT_AUDIT = ROOT / ".github/workflows/blinq-drive-content-audit.yml"


class CronWiringTests(unittest.TestCase):
    def test_original_cron_url_now_calls_read_only_content_audit(self):
        text = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("  workflow_dispatch:", text)
        self.assertIn("  drive-content-readonly:", text)
        self.assertIn("    uses: ./.github/workflows/blinq-drive-content-audit.yml", text)
        self.assertIn("      download_mb: '512'", text)
        self.assertIn("    secrets: inherit", text)
        self.assertNotIn("\n  schedule:", text)

    def test_audit_can_be_reused_without_second_cron(self):
        text = CONTENT_AUDIT.read_text(encoding="utf-8")
        self.assertIn("  workflow_call:", text)
        self.assertIn("  workflow_dispatch:", text)
        self.assertIn("        default: '512'", text)
        self.assertNotIn("\n  schedule:", text)
        self.assertIn("mode\"] == \"read_only_plan\"", text)

    def test_original_selector_cannot_write_shortcuts(self):
        text = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("          mode=plan", text)
        self.assertNotIn("            mode=apply", text)
        self.assertNotIn('export BLINQ_DRIVE_SORT_CREDENTIALS="$DRIVE_ORGANIZER_JSON"', text)
        self.assertIn('export BLINQ_DRIVE_SORT_CREDENTIALS="$DRIVE_READER_JSON"', text)

    def test_read_only_auditor_has_no_write_route(self):
        text = (ROOT / "scripts/drive_content_audit.py").read_text(encoding="utf-8")
        for expression in ('removeParents', 'def move(', 'request("PATCH"', 'request("DELETE"'):
            self.assertNotIn(expression, text)


if __name__ == "__main__":
    unittest.main()
