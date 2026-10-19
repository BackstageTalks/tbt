import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import training_status as m


class StatusTests(unittest.TestCase):
    def reader(self, *, completed=False, inaccessible=False, changed=False, incomplete=False):
        reads = 0

        def read(path):
            nonlocal reads
            if path == m.LOCK:
                if inaccessible:
                    raise RuntimeError("denied")
                reads += 1
                return {"object": {"sha": "b" if changed and reads > 1 else "a"}}
            if "/git/tags/" in path:
                return {"sha": "a", "message": f"owner={m.REPO}/actions/runs/7/attempts/2"}
            if "/attempts/2/jobs" in path:
                return {"total_count": 2 if incomplete else 1, "jobs": [{"steps": []}]}
            if path.endswith("/runs/7"):
                return {"run_attempt": 2, "status": "completed" if completed else "in_progress",
                        "conclusion": "success" if completed else None, "head_sha": "abc", "html_url": "url"}
            raise AssertionError(path)
        return read

    def test_exact_attempt_ownership(self):
        self.assertEqual(m.snapshot(7, self.reader())["lock"], "OWNED_BY_THIS_RUN")

    def test_access_error_does_not_claim_free(self):
        self.assertEqual(m.snapshot(7, self.reader(inaccessible=True))["lock"], "UNVERIFIED")

    def test_lock_race_does_not_claim_ownership(self):
        self.assertEqual(m.snapshot(7, self.reader(changed=True))["lock"], "UNVERIFIED")

    def test_success_does_not_imply_release_ready(self):
        result = m.snapshot(7, self.reader(completed=True))
        self.assertEqual(result["state"], "WORKFLOW_SUCCEEDED")
        self.assertEqual(result["release_readiness"], "NOT_VERIFIED")

    def test_truncated_jobs_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, "Incomplete"):
            m.snapshot(7, self.reader(incomplete=True))
