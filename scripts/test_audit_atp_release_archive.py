#!/usr/bin/env python3
"""Offline fixtures for independent GitHub Release archive QA."""
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from audit_atp_release_archive import audit


class ArchiveAuditTests(unittest.TestCase):
    def make_archive(self, folder, include_tournament=True, include_stats=True,
                     malicious=False):
        path = folder / "checkpoint.tar.gz"
        prefix = "data/atptour/"
        year = 2008
        asset = {
            prefix + "archive/2008/_discovery.json":
                json.dumps({"urls": ["https://www.atptour.com/en/scores/archive/test/777/2008/results"]}).encode(),
        }
        if include_tournament:
            row = {"year": 2008, "source_match_id": "atptour:2008:777:ms001",
                   "match_stats_urls": ["https://www.atptour.com/en/scores/match-stats/archive/2008/777/ms001"]}
            asset[prefix + "archive/2008/777-test.jsonl"] = (json.dumps(row) + "\n").encode()
        if include_stats:
            asset[prefix + "match_stats/2008/777/ms001.json"] = json.dumps(
                {"source_match_id": "atptour:2008:777:ms001",
                 "tables": [{"rows": [["1", "2"]]}], "visible_text": "Aces 5 7 Break Points 2 3 1st Serve 65% 70% " * 4}).encode()
        if malicious:
            asset["../../outside.json"] = b"{}"
        with tarfile.open(path, "w:gz") as tar:
            for name, blob in asset.items():
                metadata = tarfile.TarInfo(name)
                metadata.size = len(blob)
                tar.addfile(metadata, io.BytesIO(blob))
        sha = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        return path, sha

    def test_complete_and_sha_verified(self):
        with tempfile.TemporaryDirectory() as d:
            path, sha = self.make_archive(Path(d))
            result = audit(path, 2008, sha)
            self.assertTrue(result["source_archive_complete"])
            self.assertEqual(result["tournaments_found"], 1)
            self.assertEqual(result["linked_match_stats"], 1)
            self.assertEqual(result["stats_with_nonempty_tables"], 1)
            self.assertEqual(result["stats_with_text_over_100_chars"], 1)
            self.assertEqual(result["stats_with_numeric_serve_text"], 1)

    def test_missing_tournament_not_green(self):
        with tempfile.TemporaryDirectory() as d:
            path, sha = self.make_archive(Path(d), include_tournament=False)
            result = audit(path, 2008, sha)
            self.assertFalse(result["source_archive_complete"])
            self.assertEqual(result["missing_tournaments"], 1)

    def test_missing_match_stats_not_green(self):
        with tempfile.TemporaryDirectory() as d:
            path, sha = self.make_archive(Path(d), include_stats=False)
            result = audit(path, 2008, sha)
            self.assertFalse(result["source_archive_complete"])
            self.assertEqual(result["missing_match_stats"], 1)

    def test_sha_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path, sha = self.make_archive(Path(d))
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                audit(path, 2008, "sha256:" + "0" * 64)

    def test_archive_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path, sha = self.make_archive(Path(d), malicious=True)
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                audit(path, 2008, sha)


if __name__ == "__main__":
    unittest.main(verbosity=2)
