import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import train_candidate as m


class TrainingTests(unittest.TestCase):
    def test_busy_writer_never_dispatches(self):
        with self.assertRaisesRegex(RuntimeError, "busy"):
            m.start("main", "top-7.2.1", inspect=lambda: "BUSY",
                    dispatch=lambda _: self.fail("Dispatched with busy lock"))

    def test_queued_training_never_dispatches(self):
        def read(path):
            return {"sha": "a"} if "/commits/" in path else {"workflow_runs": [{"html_url": "existing"}]}
        with self.assertRaisesRegex(RuntimeError, "already"):
            m.start("main", "standard", read=read, inspect=lambda: "FREE",
                    dispatch=lambda _: self.fail("Duplicate dispatch"))

    def test_moved_ref_never_dispatches(self):
        commits = iter(["a", "b"])
        def read(path):
            return {"sha": next(commits)} if "/commits/" in path else {"workflow_runs": []}
        with self.assertRaisesRegex(RuntimeError, "changed"):
            m.start("main", "standard", read=read, inspect=lambda: "FREE",
                    dispatch=lambda _: self.fail("Moved ref dispatch"))

    def test_dispatch_preserves_ref_profile_and_does_not_claim_success(self):
        commands = []
        def read(path):
            return {"sha": "a"} if "/commits/" in path else {"workflow_runs": []}
        result = m.start("experiment/x", "top-7.2.1", read=read,
                         inspect=lambda: "FREE", dispatch=commands.append)
        self.assertEqual(result["state"], "DISPATCHED_NOT_VERIFIED")
        self.assertIn("experiment/x", commands[0])
        self.assertIn("training_profile=top-7.2.1", commands[0])

    def test_empty_candidate_is_not_a_model(self):
        rows = m.candidates(lambda _: [{"tag_name": "blinq-candidate-frozen-7-1", "html_url": "url", "assets": []}])
        self.assertEqual(rows[0]["state"], "INCOMPLETE")
        self.assertFalse(rows[0]["release_ready"])

    def test_assets_do_not_prove_quality(self):
        rows = m.candidates(lambda _: [{"tag_name": "blinq-candidate-frozen-7-1", "html_url": "url",
            "assets": [{"name": n, "size": 5} for n in ("model.joblib", "training_report.json", "_tbt_bundle_manifest.json")]}])
        self.assertEqual(rows[0]["state"], "ASSETS_PRESENT_UNVERIFIED")
        self.assertFalse(rows[0]["release_ready"])
