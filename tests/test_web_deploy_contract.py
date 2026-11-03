"""Regression tests for the small, shared web deploy contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from optimize_web_assets import ASSETS as OPTIMIZER_ASSETS  # noqa: E402
from stamp_web_deployment import ASSETS as STAMP_ASSETS, stamp  # noqa: E402
from web_deploy_contract import DEPLOYED_ASSETS, OPTIMIZED_ASSETS, read_release  # noqa: E402


class WebDeployContractTests(unittest.TestCase):
    def test_optimizer_and_stamper_preserve_exact_asset_sets(self):
        self.assertEqual(OPTIMIZER_ASSETS, ("app.js", "blinq-app.css"))
        self.assertEqual(STAMP_ASSETS, ("blinq-app.css", "app.js", "auth.js", "responsive.js"))
        self.assertEqual(OPTIMIZER_ASSETS, OPTIMIZED_ASSETS)
        self.assertEqual(STAMP_ASSETS, DEPLOYED_ASSETS)

    def test_twice_stamped_artifacts_remain_identical_and_hash_match(self):
        with tempfile.TemporaryDirectory() as folder:
            web = Path(folder)
            release = {"patch": "736-r33", "visual_revision": "test-visual"}
            (web / "release.json").write_text(json.dumps(release), encoding="utf-8")
            self.assertEqual(read_release(web), release)
            sha = "1" * 40
            html = ['  <title>BlinQ · Tennis Intelligence</title>']
            for name in DEPLOYED_ASSETS:
                data = (name * 5).encode("utf-8")
                (web / name).write_bytes(data)
                html.append(f'<script src="/{name}?v=7360&p=33"></script>')
            (web / "index.html").write_text("\n".join(html) + "\n", encoding="utf-8")
            first = stamp(web, sha)
            html_first = (web / "index.html").read_text(encoding="utf-8")
            second = stamp(web, sha)
            self.assertEqual(first, second)
            self.assertEqual((web / "index.html").read_text(encoding="utf-8"), html_first)
            self.assertEqual(first["git_sha"], sha)
            self.assertEqual(html_first.count('name="blinq-deployment-sha"'), 1)
            self.assertEqual(html_first.count("&deploy=" + sha[:12]), 4)
            self.assertEqual(len(first["files_sha256"]), 4)
            for name in DEPLOYED_ASSETS:
                self.assertEqual(first["files_sha256"][name],
                                 hashlib.sha256((web / name).read_bytes()).hexdigest())
            self.assertEqual(json.loads((web / "deployment.json").read_text()), first)


if __name__ == "__main__":
    unittest.main()
