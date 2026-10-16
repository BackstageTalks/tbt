"""No-network, no-credential regression tests for read-only lock diagnostics."""
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_cdb_lock_liveness as m

TAG_SHA = "a" * 40
MANIFEST_SHA = "b" * 64
RUN_ID = "38890966561"


def fixture(*, status="in_progress", conclusion=None,
            lock_changed=False, release_changed=False,
            malformed_owner=False, bad_digest=False):
    calls = {"lock": 0, "release": 0}
    def fetch(repo, path):
        if path == m.LOCK_PATH:
            calls["lock"] += 1
            sha = "f" * 40 if lock_changed and calls["lock"] == 2 else TAG_SHA
            return {"object": {"sha": sha}}
        if path == m.TAG_PATH + TAG_SHA:
            return {"sha": TAG_SHA, "message": (
                "owner=untrusted/actions/runs/123/attempts/1" if malformed_owner
                else f"owner={m.APP_REPO}/actions/runs/{RUN_ID}/attempts/1")}
        if path == m.RELEASE_PATH:
            calls["release"] += 1
            digest = "broken" if bad_digest else "sha256:" + MANIFEST_SHA
            if release_changed and calls["release"] == 2:
                digest = "sha256:" + "c" * 64
            return {"id": 42, "updated_at": "2026-10-16", "assets": [
                {"name": "history_manifest.json", "digest": digest}]}
        if path == f"actions/runs/{RUN_ID}":
            return {"id": int(RUN_ID), "status": status, "conclusion": conclusion}
        raise AssertionError((repo, path))
    return fetch, calls


class LockAuditTests(unittest.TestCase):
    def test_live_writer_always_blocks_unlock(self):
        f, c = fixture()
        r = m.assess(f)
        self.assertEqual(r["classification"], "ACTIVE_OR_PENDING_OWNER_DO_NOT_UNLOCK")
        self.assertFalse(r["lock_release_authorized"])
        self.assertEqual(r["delete_attempts"], 0)
        self.assertEqual((c["lock"], c["release"]), (2, 2))

    def test_completed_owner_is_only_candidate(self):
        f, _ = fixture(status="completed", conclusion="failure")
        r = m.assess(f)
        self.assertEqual(r["classification"], "COMPLETED_OWNER_STALE_CANDIDATE_ONLY")
        self.assertFalse(r["canonical_write_authorized"])
        self.assertFalse(r["lock_release_authorized"])

    def test_ref_changed_during_check_does_not_authorize_unlock(self):
        f, _ = fixture(lock_changed=True)
        r = m.assess(f)
        self.assertEqual(r["classification"], "LOCK_CHANGED_DURING_AUDIT")
        self.assertFalse(r["lock_release_authorized"])

    def test_manifest_changed_during_check_does_not_authorize_import(self):
        f, _ = fixture(release_changed=True)
        r = m.assess(f)
        self.assertEqual(r["classification"], "CANONICAL_RELEASE_CHANGED_DURING_AUDIT")
        self.assertFalse(r["canonical_write_authorized"])

    def test_untrusted_owner_rejected(self):
        f, _ = fixture(malformed_owner=True)
        with self.assertRaisesRegex(m.AuditBlocked, "unrecognized writer owner"):
            m.assess(f)

    def test_invalid_manifest_digest_rejected(self):
        f, _ = fixture(bad_digest=True)
        with self.assertRaisesRegex(m.AuditBlocked, "digest missing or malformed"):
            m.assess(f)

    def test_status_missing_fails_closed(self):
        f, _ = fixture(status="unknown")
        with self.assertRaisesRegex(m.AuditBlocked, "status unverified"):
            m.assess(f)

    def test_completed_without_conclusion_fails_closed(self):
        f, _ = fixture(status="completed")
        with self.assertRaisesRegex(m.AuditBlocked, "lacks conclusion"):
            m.assess(f)

    def test_missing_gh_token_fails_closed(self):
        import os
        old = os.environ.pop("GH_TOKEN", None)
        try:
            with self.assertRaisesRegex(m.AuditBlocked, "GH_TOKEN required"):
                m.gh_get(m.DATA_REPO, m.LOCK_PATH)
        finally:
            if old is not None:
                os.environ["GH_TOKEN"] = old


if __name__ == "__main__":
    unittest.main()
