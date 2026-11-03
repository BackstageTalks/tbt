"""Offline contract tests for read-only frontend HTTP transport measurements."""
from __future__ import annotations

import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from measure_frontend_delivery import ASSETS, measure, public_origin  # noqa: E402


FIXTURES = {path: (f"data for {path} " * 300).encode() for path in ASSETS}
FIXTURES["/deployment.json"] = json.dumps({
    "git_sha": "test-sha",
    "files_sha256": {
        path.lstrip("/"): hashlib.sha256(FIXTURES[path]).hexdigest()
        for path in ("/app.js", "/auth.js", "/responsive.js", "/blinq-app.css")
    },
}).encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path not in FIXTURES:
            self.send_error(404)
            return
        no_store = path == "/app.js"
        if not no_store and self.headers.get("If-None-Match") == '"fixture-v1"':
            self.send_response(304)
            self.send_header("ETag", '"fixture-v1"')
            self.end_headers()
            return
        payload = FIXTURES[path]
        encoding = self.headers.get("Accept-Encoding", "identity")
        self.send_response(200)
        self.send_header("Content-Type", "application/json" if path.endswith(".json") else "text/plain")
        self.send_header("Cache-Control", "no-store" if no_store else "public, max-age=60")
        self.send_header("ETag", '"fixture-v1"')
        if encoding == "gzip":
            payload = gzip.compress(payload)
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class FrontendDeliveryTest(unittest.TestCase):
    def test_reject_non_https_credentials_and_query(self):
        for origin in ("http://example.com", "https://user:pass@example.com",
                       "https://example.com/p", "https://example.com/?key=secret"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                public_origin(origin)
        self.assertEqual(public_origin("https://example.com/"), "https://example.com")

    def test_measure_bytes_compression_cache_revalidation_and_manifest_hashes(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = measure(f"http://127.0.0.1:{server.server_port}", require_https=False)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(result["deployed_git_sha"], "test-sha")
        self.assertEqual(len(result["deployment_hash_check"]), 4)
        self.assertTrue(all(result["deployment_hash_check"].values()))
        self.assertLess(result["totals"]["gzip"], result["totals"]["identity"])
        self.assertEqual(result["assets"]["/app.js"]["conditional_identity"]["status"], 200)
        self.assertEqual(result["assets"]["/auth.js"]["conditional_identity"]["status"], 304)
        self.assertEqual(result["assets"]["/app.js"]["identity"]["headers"]["cache-control"], "no-store")
        self.assertEqual(result["assets"]["/auth.js"]["br"]["headers"].get("content-encoding"), None)


if __name__ == "__main__":
    unittest.main()
