"""Regression: source pin updates cannot silently change historical contracts."""
import unittest

from audit_minmaxxxer_cdb_importability import (
    FILES, FILES_WEEKLY_20261116, _files_for_revision,
)


class PinnedHFSourceContractsTest(unittest.TestCase):
    def test_existing_pinned_source_remains_the_default(self):
        self.assertEqual(_files_for_revision("2026-11-09"), FILES)
        self.assertEqual(FILES["atp_matches_2026.csv"], ("ATP", 773871))
        self.assertEqual(FILES["wta_matches_2026.csv"], ("WTA", 739770))

    def test_20261116_weekly_inventory_is_exact_and_separate(self):
        self.assertEqual(_files_for_revision("2026-11-16"), FILES_WEEKLY_20261116)
        self.assertEqual(FILES_WEEKLY_20261116, {
            "atp_matches_2025.csv": ("ATP", 832145),
            "wta_matches_2025.csv": ("WTA", 793966),
            "atp_matches_2026.csv": ("ATP", 781669),
            "wta_matches_2026.csv": ("WTA", 743966),
        })
        self.assertNotEqual(FILES_WEEKLY_20261116, FILES)

    def test_unknown_revision_fails_closed(self):
        for value in ("", "main", "2026-11-17", "../source"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Unrecognized pinned"):
                    _files_for_revision(value)


if __name__ == "__main__":
    unittest.main()
