import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("orphan", ROOT / "scripts/recover_exact_orphan_cdb_lock_once.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class TestOneShotOrphanRecovery(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.status = "completed"
        self.conclusion = "failure"
        self.attempt = 1
        self.ref_sha = mod.ABANDONED_SHA
        self.owner = mod.OWNER
        self.jobs_status = "completed"
        self.deleted = False

    def api(self, endpoint, method="GET"):
        self.calls.append((endpoint,method))
        if endpoint.endswith("git/ref/tags/blinq-cdb-global-writer"):
            if self.deleted: raise RuntimeError("GitHub 404 (HTTP 404)")
            return {"object":{"sha":self.ref_sha}}
        if endpoint.endswith("git/refs/tags/blinq-cdb-global-writer") and method=="DELETE":
            self.deleted=True
            return {}
        if endpoint.endswith(f"actions/runs/{mod.FAILED_RUN}"):
            return {"id":mod.FAILED_RUN,"status":self.status,
                    "conclusion":self.conclusion,"run_attempt":self.attempt}
        if endpoint.endswith(f"actions/runs/{mod.FAILED_RUN}/jobs?per_page=100"):
            return {"total_count":1,"jobs":[{"status":self.jobs_status}]}
        if endpoint.endswith(f"git/tags/{mod.ABANDONED_SHA}"):
            return {"message":f"owner={self.owner}","object":{"type":"commit"}}
        raise AssertionError(endpoint)

    def test_exact_terminal_owner_is_only_deletion(self):
        self.assertEqual(mod.recover(self.api),"recovered_single_confirmed_abandoned_lock")
        self.assertTrue(self.deleted)
        self.assertEqual(sum(m=="DELETE" for _,m in self.calls),1)

    def test_other_owner_never_deleted(self):
        self.ref_sha="1234"
        self.assertEqual(mod.recover(self.api),"different_owner_intact")
        self.assertFalse(self.deleted)

    def test_live_or_rerun_owner_never_deleted(self):
        for status, conclusion, attempt in [
            ("in_progress",None,1),("queued",None,1),("completed","success",1),
            ("completed","failure",2)]:
            self.status,self.conclusion,self.attempt=status,conclusion,attempt
            with self.assertRaisesRegex(RuntimeError,"not provably terminal"):
                mod.recover(self.api)
            self.assertFalse(self.deleted)

    def test_job_in_progress_blocks_deletion(self):
        self.jobs_status="in_progress"
        with self.assertRaisesRegex(RuntimeError,"jobs not all terminal"):
            mod.recover(self.api)
        self.assertFalse(self.deleted)

    def test_mismatched_tag_owner_blocks_deletion(self):
        self.owner="BackstageTalks/tbt/actions/runs/other/attempts/1"
        with self.assertRaisesRegex(RuntimeError,"owner mismatch"):
            mod.recover(self.api)
        self.assertFalse(self.deleted)

    def test_no_tag_is_safe_noop(self):
        self.deleted=True
        self.assertEqual(mod.recover(self.api),"no_lock")

    def test_race_before_delete_blocks_recovery(self):
        seen=0
        def changed(endpoint,method="GET"):
            nonlocal seen
            v=self.api(endpoint,method)
            if endpoint.endswith("git/ref/tags/blinq-cdb-global-writer"):
                seen+=1
                if seen==2: v["object"]["sha"]="new-writer"
            return v
        with self.assertRaisesRegex(RuntimeError,"Lock moved"):
            mod.recover(changed)
        self.assertFalse(self.deleted)

if __name__ == "__main__":
    unittest.main()
