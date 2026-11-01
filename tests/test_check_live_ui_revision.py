"""Offline regression tests for the live Azure UI drift watchdog."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.check_live_ui_revision import FRONTEND_FILES, STAMPED_FILES, original_index, revision_files, sha256, verify_once

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

    def test_revision_files_reads_actual_git_commit_not_newer_checkout(self):
        root = self.web / "checkout"
        web = root / "web"
        web.mkdir(parents=True)
        for name in (*FRONTEND_FILES, "index.html"):
            shutil.copy2(self.web / name, web / name)
        def git(*args):
            return subprocess.run(["git", "-C", str(root), *args],
                                  check=True, capture_output=True).stdout.decode().strip()
        git("init", "-q")
        git("config", "user.email", "ci@example.test")
        git("config", "user.name", "CI")
        git("add", "web")
        git("commit", "-qm", "first deployed frontend")
        deployed_sha = git("rev-parse", "HEAD")
        original = revision_files(web, deployed_sha)
        (web / "app.js").write_text("newer main release")
        (web / "index.html").write_text("<html>new main</html>")
        git("add", "web")
        git("commit", "-qm", "later checkout revision")
        checked = revision_files(web, deployed_sha)
        self.assertEqual(checked, original)
        self.assertNotEqual(checked["app.js"], (web / "app.js").read_bytes())

    def test_direct_execution_can_import_the_pinned_optimizer(self):
        # python scripts/check_live_ui_revision.py puts scripts/, not the
        # repository root, on sys.path. Reproduce that isolated import shape.
        scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "import check_live_ui_revision as w; "
            "assets, build = w.load_pinned_optimizer(); "
            "assert assets == ('app.js', 'blinq-app.css'); "
            "assert callable(build)"
        )
        subprocess.run(
            [sys.executable, "-I", "-c", code, str(scripts_dir)],
            check=True, capture_output=True, text=True, cwd=self.web,
        )

    def test_exact_optimized_deployment_passes_and_modified_js_is_rejected(self):
        # The production pipeline intentionally rewrites whitespace in JS/CSS.
        # Trust neither the live checksum manifest nor the CDN without
        # reproducing those bytes from the immutable Git sources.
        release = json.loads(self.files["/release.json"])
        visual = release["visual_revision"]
        app = (f"/* BlinQ visual revision: {visual} */\n"
               "function verifiedAceProviderOdds(){}").encode()
        css = (b"/* BlinQ runtime patch 7.3.6-r61 */\n"
               b"/* BlinQ visual revision green-login-loader-20260924 */\nbody{}")
        self.files["/app.js"] = app
        self.files["/blinq-app.css"] = css
        meta = json.loads(self.files["/deployment.json"])
        for name in ("app.js", "blinq-app.css"):
            meta["files_sha256"][name] = sha256(self.files["/" + name])
        self.files["/deployment.json"] = json.dumps(meta).encode()

        calls = []
        def reproducible_build(raw):
            calls.append(True)
            return {**raw, "app.js": app, "blinq-app.css": css}

        self.assertEqual(verify_once(
            self.web, "https://test.invalid", self.fetch,
            optimized_builder=reproducible_build
        ), SHA)
        self.assertEqual(len(calls), 1)

        # Even a forged, internally consistent deployment.json cannot pass
        # if its JS differs from the reproducibly optimized Git source.
        self.files["/app.js"] = app + b"malicious change"
        meta["files_sha256"]["app.js"] = sha256(self.files["/app.js"])
        self.files["/deployment.json"] = json.dumps(meta).encode()
        with self.assertRaisesRegex(ValueError, "app.js"):
            verify_once(self.web, "https://test.invalid", self.fetch,
                        optimized_builder=reproducible_build)

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
