"""Proof that the existing 2025/26 CDB audit request only dispatches readers."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MARKER=".github/cdb-gap-20261015-request.json"
READERS={
    "blinq-drive-cdb-gap-once.yml",
    "blinq-current-source-field-delta.yml",
    "blinq-uploaded-crosswalk-recheck-once.yml",
}
WRITERS={"blinq-uploaded-2025-26-cdb-guarded.yml"}


class RequestWiringTests(unittest.TestCase):
    def test_all_readers_are_dispatched(self):
        for name in READERS:
            with self.subTest(workflow=name):
                source=(ROOT/".github/workflows"/name).read_text()
                self.assertIn("- "+MARKER,source)
                self.assertIn("branches: [main]",source)

    def test_writer_not_dispatched_by_request(self):
        for name in WRITERS:
            source=(ROOT/".github/workflows"/name).read_text()
            self.assertNotIn(MARKER,source)

    def test_request_is_restricted_to_read_only(self):
        import json
        data=json.loads((ROOT/MARKER).read_text())
        self.assertEqual(data["mode"],"read_only")
        self.assertIs(data["allow_cdb_writes"],False)
        self.assertIs(data["allow_drive_writes"],False)
        self.assertEqual(data["year_scope"],[2025,2026])


if __name__ == "__main__":
    unittest.main()
