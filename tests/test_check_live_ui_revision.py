"""Offline regression tests for the live Azure UI drift watchdog."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_live_ui_revision import FRONTEND_FILES, STAMPED_FILES, original_index, sha256, verify_once

SHA = "a" * 40


class UiWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.web = Path(self.tmp.name)
        self.files = {}
        for name in FRONTEND_FILES:
            data = b'{"release":"7.3.6","patch":"736-r61","visual_revision":"green-login-loader-20260924"}' if name == "release.json" else (b"current_" + name.encode())
            (self.web / name).write_bytes(data)
            self.files["/" + name] = data

        self.html = '<!doctype html>\n<head>\n  <title>BlinQ</title>\n  <script src="/app.js?v=1"></script>\n</head>\n'
        (self.web / "index.html").write_text(self.html, encoding="utf-8")
        live_html = self.html.replace(
            "  <title>BlinQ</title>",
            f'  <meta name="blinq-deployment-sha" content="{SHA}" />\n  <title>BlinQ</title>',
        ).replace('app.js?v=1"', f'app.js?v=1&deploy={SHA[:12]}"')
        self.files["/"] = live_html.encode()
        self.files["/follow-the-data/"] = live_html.encode()
        marker = {
            "git_sha": SHA,
            "patch": "736-r61",
            "visual_revision": "green-login-loader-20260924",
            "files_sha256": {
                name: sha256(self.files["/" + name]) for name in STAMPED_FILES
            },
        }
        self.files["/deployment.json"] = json.dumps(marker).encode()

    def fetch(self, url):
        route = url.split("?")[0].split("test.invalid")[-1]
        return self.files[route]

    def test_current_site_passes_when_deployment_sha_is_not_main(self):
        self.assertEqual(verify_once(self.web, "https://test.invalid", self.fetch), SHA)

    def test_newer_checkout_is_not_falsely_treated_as_live_drift(self):
        # Azure's valid deployed SHA is older than the CI checkout. The
        # immutable release is the source of truth; a later HEAD is unrelated.
        original = {name: (self.web / name).read_bytes()
                    for name in (*FRONTEND_FILES, "index.html")}
        (self.web / "app.js").write_bytes(b"new_head_app")
        (self.web / "index.html").write_text("<html>new main HTML</html>")
        expected = lambda _web, sha: original if sha == SHA else None
        self.assertEqual(verify_once(self.web, "https://test.invalid", self.fetch,
                                     source_loader=expected), SHA)
        # A genuine cross-route drift still fails even against the right SHA.
        self.files["/follow-the-data/"] = b"<html>broken SPA route</html>"
        with self.assertRaisesRegex(ValueError, "/follow-the-data/"):
            verify_once(self.web, "https://test.invalid", self.fetch,
                        source_loader=expected)

    def test_invalid_revision_fails_closed_even_if_current_files_match(self):
        with self.assertRaisesRegex(ValueError, "Cannot verify"):
            verify_once(self.web, "https://test.invalid", self.fetch,
                        source_loader=lambda *_: (_ for _ in ()).throw(
                            ValueError("Cannot verify exact deployed revision from Git history")))

    def test_detects_stale_app_even_with_success_http(self):
        self.files["/app.js"] = b"old_application"
        with self.assertRaisesRegex(ValueError, "app.js"):
            verify_once(self.web, "https://test.invalid", self.fetch)

    def test_detects_stale_spa_route_even_if_root_is_current(self):
        self.files["/follow-the-data/"] = b"<html>old login</html>"
        with self.assertRaisesRegex(ValueError, "/follow-the-data/"):
            verify_once(self.web, "https://test.invalid", self.fetch)

    def test_detects_mismatched_html_even_with_valid_sha(self):
        self.files["/"] = self.files["/"].replace(b"BlinQ", b"OldBlinQ")
        with self.assertRaisesRegex(ValueError, "HTML on /"):
            verify_once(self.web, "https://test.invalid", self.fetch)

    def test_detects_invalid_deployment_integrity(self):
        meta = json.loads(self.files["/deployment.json"])
        meta["files_sha256"]["app.js"] = "0" * 64
        self.files["/deployment.json"] = json.dumps(meta).encode()
        with self.assertRaisesRegex(ValueError, "checksum: app.js"):
            verify_once(self.web, "https://test.invalid", self.fetch)

    def test_stamp_reversal_keeps_unrelated_query_parts(self):
        html = '<meta name="blinq-deployment-sha" content="' + SHA + '" />\n<script src="/app.js?v=1&deploy=' + SHA[:12] + '&other=1"></script>'
        self.assertIn("v=1&other=1", original_index(html))
        self.assertNotIn(SHA, original_index(html))


if __name__ == "__main__":
    unittest.main()
