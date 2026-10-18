"""No-network contract tests for the CDB writer read-only training preflight."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import wait_for_cdb_writer_idle as m

TAG = "a" * 40


def fake_get(*, owner_status="in_progress", owner_attempt=1, changed=False):
    calls = {"lock": 0}

    def get(path, *, lock_missing_ok=False):
        if path == m.LOCK:
            calls["lock"] += 1
            sha = "b" * 40 if changed and calls["lock"] == 2 else TAG
            return {"object": {"sha": sha}}
        if path == f"repos/{m.DATA_REPO}/git/tags/{TAG}":
            return {"sha": TAG, "message": "owner=BackstageTalks/tbt/actions/runs/39143054902/attempts/1"}
        if path == "repos/BackstageTalks/tbt/actions/runs/39143054902":
            return {"id": 39143054902, "status": owner_status, "run_attempt": owner_attempt}
        if path == "repos/BackstageTalks/tbt/actions/runs/39143054902/attempts/1/jobs?per_page=100":
            return {"total_count": 1, "jobs": [{"status": "completed"}]}
        raise AssertionError("Unexpected non-readonly endpoint: " + path)
    return get


class PreflightTests(unittest.TestCase):
    def test_active_owner_waits_without_unlock(self):
        self.assertEqual(m.snapshot(fake_get()), "BUSY")

    def test_idle_requires_two_consistent_absent_reads(self):
        self.assertEqual(m.snapshot(lambda path, **kw: None), "FREE")
        calls = {"n": 0}
        def changed(path, **kw):
            calls["n"] += 1
            return None if calls["n"] == 1 else {"object": {"sha": TAG}}
        self.assertEqual(m.snapshot(changed), "BUSY")

    def test_changed_owner_is_not_claimed_idle(self):
        self.assertEqual(m.snapshot(fake_get(changed=True)), "BUSY")

    def test_completed_owner_requires_manual_scoped_recovery(self):
        with self.assertRaisesRegex(m.GateBlocked, "manual owner-scoped recovery"):
            m.snapshot(fake_get(owner_status="completed"))

    def test_attempt_rerun_mismatch_fails_closed(self):
        with self.assertRaisesRegex(m.GateBlocked, "cannot be independently verified"):
            m.snapshot(fake_get(owner_attempt=2))

    def test_bad_owner_ref_fails_closed(self):
        def bad(path, **kw):
            if path == m.LOCK:
                return {"object": {"sha": TAG}}
            return {"sha": TAG, "message": "owner=other/repo/actions/runs/5/attempts/1"}
        with self.assertRaisesRegex(m.GateBlocked, "Unrecognized global writer"):
            m.snapshot(bad)

    def test_wait_no_implicit_acquire_or_delete(self):
        states = iter(["BUSY", "BUSY", "FREE"])
        sleeps = []
        m.wait(50, 10, inspect=lambda: next(states), clock=lambda: 0,
               sleep=lambda seconds: sleeps.append(seconds))
        self.assertEqual(sleeps, [10, 10])

    def test_bounded_timeout_fails_closed(self):
        times = iter([0, 1, 4, 10])
        with self.assertRaisesRegex(m.GateBlocked, "remained busy"):
            m.wait(5, 2, inspect=lambda: "BUSY", clock=lambda: next(times),
                   sleep=lambda t: None)

    def test_404_vs_permission_failure(self):
        from types import SimpleNamespace
        with patch.dict(m.os.environ, {"GH_TOKEN": "fake"}):
            with patch.object(m.subprocess, "run", return_value=SimpleNamespace(
                    returncode=1, stderr="gh: Not Found (HTTP 404)", stdout="")):
                self.assertIsNone(m.gh_get(m.LOCK, lock_missing_ok=True))
                with self.assertRaises(m.GateBlocked):
                    m.gh_get("repos/BackstageTalks/tbt/actions/runs/1")
            with patch.object(m.subprocess, "run", return_value=SimpleNamespace(
                    returncode=1, stderr="gh: Forbidden (HTTP 403)", stdout="")):
                with self.assertRaises(m.GateBlocked):
                    m.gh_get(m.LOCK, lock_missing_ok=True)


if __name__ == "__main__":
    unittest.main()
