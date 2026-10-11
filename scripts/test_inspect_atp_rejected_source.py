#!/usr/bin/env python3
"""Synthetic, offline regression tests for rejected ATP page diagnostics."""
import gzip
import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from inspect_atp_rejected_source import inspect_html, inspect_checkpoint


class RejectedHtmlTests(unittest.TestCase):
    def test_shell_detected(self):
        result=inspect_html('<html><script id="__NEXT_DATA__">{"noStats":1}</script>'
                            '<body>ATP Tour</body></html>')
        self.assertTrue(result["client_rendered_shell"])
        self.assertFalse(result["serve_stat_terms"])

    def test_provider_denial_detected(self):
        result=inspect_html("<html>Access denied — please wait</html>")
        self.assertTrue(result["blocked_or_denied"])
        self.assertFalse(result["serve_stat_terms"])

    def test_stat_terms_detected(self):
        result=inspect_html("<main>Aces 3 7, First Serve 67% 70%</main>")
        self.assertTrue(result["serve_stat_terms"])

    def test_sha_pinned_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"source.tar.gz"
            page=gzip.compress(b"<html><script>window.__next_f=[]</script></html>")
            with tarfile.open(path,"w:gz") as archive:
                member=tarfile.TarInfo("data/atptour/match_stats/2006/1/ms1.unverified.html.gz")
                member.size=len(page)
                archive.addfile(member,io.BytesIO(page))
            digest="sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()
            report=inspect_checkpoint(path,digest)
            self.assertEqual(report["rejected_captures"],1)
            self.assertEqual(report["provider_requests"],0)
            self.assertEqual(report["feature_counts"]["client_rendered_shell"],1)
            with self.assertRaisesRegex(ValueError,"SHA-256"):
                inspect_checkpoint(path,"sha256:"+"0"*64)


if __name__=="__main__":
    unittest.main(verbosity=2)
