import csv
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from drive_repo_source_sheet import drive_inventory, generate, repo_inventory, release_inventory, safe_cell

class AuditSheetTests(unittest.TestCase):
    def test_git_is_pinned_to_current_commit_and_rejects_truncated_tree(self):
        sha = "a" * 40
        calls = []
        def fetch(path):
            calls.append(path)
            if "/branches/" in path:
                return {"commit": {"sha": sha}}
            return {"truncated": False, "tree": [
                {"type": "blob", "path": "research/serve.csv", "sha": "b"*40, "size": 123},
                {"type": "tree", "path": "research", "sha": "c"*40},
            ]}
        items, commit = repo_inventory("BackstageTalks/tbt-data", fetch=fetch)
        self.assertEqual(commit, sha)
        self.assertEqual(len(items), 1)
        self.assertIn(sha, calls[-1])
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            repo_inventory("BackstageTalks/tbt", fetch=lambda p:
                {"commit": {"sha": sha}} if "/branches/" in p else {"truncated": True, "tree": []})

    def test_release_metadata_is_bounded_and_incomplete_scope_is_explicit(self):
        call_list = []
        def fetch(url):
            call_list.append(url)
            return [{"tag_name": "blinq-drive-source-inventory-latest-v1",
                     "assets": [{"id": 8, "name": "ignore.json"}]}] + [
                {"tag_name": "dataset", "assets": [{"id": 9 + i,
                  "name": "serve.csv", "digest": "sha256:ab", "size": 42}]}
                for i in range(99)]
        rows, complete = release_inventory("BackstageTalks/tbt-data", fetch=fetch, max_pages=1)
        self.assertFalse(complete)
        self.assertEqual(len(rows), 99)
        self.assertEqual(rows[0]["status"], "RELEASE_METADATA_ONLY_NOT_BYTES_VERIFIED")
        self.assertEqual(len(call_list), 1)
        with self.assertRaises(ValueError):
            release_inventory("BackstageTalks/tbt", fetch=fetch)
        rows, complete = release_inventory("BackstageTalks/tbt-data", fetch=lambda p: [], max_pages=1)
        self.assertTrue(complete)
        self.assertEqual(rows, [])
    def test_drive_shortcuts_ignored_and_matching_inventory_required(self):
        inventory = [
            {"id": "d1", "name": "serve_stats.csv", "mimeType": "text/csv",
             "version": "2", "size": "100", "modifiedTime": "2026-10-14"},
            {"id": "s1", "name": "serve_stats.csv", "mimeType": "application/vnd.google-apps.shortcut"},
        ]
        reports = [{"id": "d1", "status": "CACHED"},
                   {"id": "s1", "status": "NEEDS_FORMAT_ADAPTER"}]
        self.assertEqual(len(drive_inventory(inventory, reports)), 1)
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            drive_inventory(inventory, reports[:1])

    def test_new_changed_removed_and_baseline_not_falsely_new(self):
        drive = [{"id": "drive:d1", "source": "Google Drive", "name": "serve.csv",
                  "size": 10, "fingerprint": "d1", "link": "https://example.invalid",
                  "mime": "text/csv", "status": "CACHED"}]
        repos = {"BackstageTalks/tbt": [], "BackstageTalks/tbt-data": [{
            "id": "git:BackstageTalks/tbt-data:research/odds.csv",
            "source": "BackstageTalks/tbt-data", "name": "research/odds.csv",
            "size": 5, "fingerprint": "aaa", "link": "https://example.invalid",
            "mime": ".csv", "status": "REPO_NOT_FIELD_MATCHED"}]}
        cmp = {"cdb_writes": 0, "canonical_rows": 5,
               "comparison": {"candidate_missing_fields": 2}}
        with TemporaryDirectory() as folder:
            path = Path(folder)
            first = generate(drive, repos, {}, cmp, None, path)
            self.assertEqual(first["source_counts"], {"BASELINE": 2})
            self.assertEqual((path / "nove-a-zmenene-zdroje.csv").read_text(encoding="utf-8-sig").count("\n"), 1)
            prev = json.loads((path / "source-baseline.json").read_text())
            same = generate(drive, repos, {}, cmp, prev, path)
            self.assertEqual(same["source_counts"], {"BEZ_ZMENY": 2})
            repos["BackstageTalks/tbt-data"][0]["fingerprint"] = "bbb"
            drive.clear()
            result = generate(drive, repos, {}, cmp, prev, path)
            self.assertEqual(result["source_counts"], {"UZ_NEDOSTUPNY": 1, "ZMENENY": 1})
            with (path / "nove-a-zmenene-zdroje.csv").open(encoding="utf-8-sig", newline="") as f:
                self.assertEqual(len(list(csv.DictReader(f))), 2)

    def test_fail_closed_on_writes_duplicates_and_untrusted_csv(self):
        self.assertTrue(safe_cell("=IMPORTXML('bad')").startswith("'"))
        self.assertTrue(safe_cell("+1").startswith("'"))
        with TemporaryDirectory() as folder:
            item = {"id": "dup", "source": "Google Drive", "name": "@evil.csv",
                    "size": 2, "fingerprint": "a", "link": "", "mime": "",
                    "status": ""}
            with self.assertRaisesRegex(ValueError, "read-only"):
                generate([item], {repo: [] for repo in
                    ("BackstageTalks/tbt", "BackstageTalks/tbt-data")},
                    {}, {"cdb_writes": 1}, None, Path(folder))
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                generate([item, item], {repo: [] for repo in
                    ("BackstageTalks/tbt", "BackstageTalks/tbt-data")},
                    {}, {"cdb_writes": 0}, None, Path(folder))

if __name__ == "__main__":
    unittest.main()
