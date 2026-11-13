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
from measure_frontend_delivery import ASSETS, PUBLIC_API_PROBES, measure, public_origin, probe_public_api_latency  # noqa: E402


FIXTURES = {path: (f"data for {path} " * 300).encode() for path in ASSETS}
API_FIXTURES = {"/api/v1/auth/config": b'{"enabled":true,"provider":"firebase"}',
                "/api/v1/ui-config": b'{"schema":2,"storage_available":true}'}
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
        if path not in FIXTURES and path not in API_FIXTURES:
            self.send_error(404)
            return
        no_store = path == "/app.js"
        if not no_store and self.headers.get("If-None-Match") == '"fixture-v1"':
            self.send_response(304)
            self.send_header("ETag", '"fixture-v1"')
            self.end_headers()
            return
        payload = FIXTURES[path] if path in FIXTURES else API_FIXTURES[path]
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



    def test_public_api_latency_is_read_only_bounded_and_exposes_no_body(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = probe_public_api_latency(
                f"http://127.0.0.1:{server.server_port}",
                require_https=False, rounds=2,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(result["rounds"], 2)
        self.assertEqual(set(result["samples"]), set(PUBLIC_API_PROBES))
        for path, samples in result["samples"].items():
            self.assertEqual(len(samples), 2, path)
            for sample in samples:
                self.assertEqual(sample["status"], 200)
                self.assertGreaterEqual(sample["total_ms"], sample["headers_ms"])
                self.assertGreaterEqual(sample["body_bytes"], 1)
                self.assertNotIn("payload", sample)
                self.assertNotIn("body", sample)
                self.assertNotIn("headers", sample)
                self.assertNotIn("token", str(sample).lower())
            self.assertEqual(result["summary"][path]["failed_or_non_2xx"], 0)
        self.assertNotIn("firebase", json.dumps(result))
        self.assertNotIn("storage_available", json.dumps(result))

    def test_api_probe_rejects_invalid_rounds_or_untrusted_origin(self):
        for count in (0, 6):
            with self.subTest(count=count), self.assertRaises(ValueError):
                probe_public_api_latency("https://example.com", rounds=count)
        for origin in ("http://example.com", "https://u:p@example.com"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                probe_public_api_latency(origin, rounds=1)


if __name__ == "__main__":
    unittest.main()
