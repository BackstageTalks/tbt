"""Model Lab actions are one-shot, fail-closed and never promote production."""
import json
import sys
import io
from urllib.error import HTTPError
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tbt.services import model_lab as m
from tbt.services import model_training


class FakeTable:
    def __init__(self):
        self.data = {}

    def get_entity(self, *, partition_key, row_key):
        return self.data[(partition_key, row_key)]

    def create_entity(self, entry):
        key = (entry["PartitionKey"], entry["RowKey"])
        if key in self.data:
            raise ValueError("exists")
        self.data[key] = dict(entry)

    def upsert_entity(self, entry, mode=None):
        self.data[(entry["PartitionKey"], entry["RowKey"])] = dict(entry)

    def delete_entity(self, *, partition_key, row_key):
        del self.data[(partition_key, row_key)]


def snapshot():
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "can_start": True, "reason": "Pripravené",
        "active_sha256": "a" * 64, "champion_sha256": "b" * 64,
        "candidates": [{"tag": "blinq-candidate-frozen-123-1",
                        "sha256": "c" * 64,
                        "url": "https://github.com/BackstageTalks/tbt-data/releases/tag/blinq-candidate-frozen-123-1"}],
        "runs": {name: [] for name in m.WORKFLOWS},
    }


class TestLab(unittest.TestCase):
    def setUp(self):
        self.fake = FakeTable()
        self.patcher = patch.object(m, "_table", return_value=self.fake)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.training_patcher = patch.object(m, "training_status", return_value={"can_start": True})
        self.training_patcher.start()
        self.addCleanup(self.training_patcher.stop)
        m._put("snapshot", snapshot())

    def test_import_queues_once_without_dispatching_from_admin(self):
        with patch.object(m, "github") as gh:
            result = m.start({"action": "import_drive"}, "admin")
            self.assertEqual(result["state"], "QUEUED")
            self.assertEqual(len(result["id"]), 24)
            with self.assertRaises(model_training.TrainingBlocked):
                m.start({"action": "import_drive"}, "admin")
            gh.assert_not_called()

    def test_factory_training_cannot_overlap_a_queued_shadow_or_import(self):
        # Both Admin entrypoints use the same durable Azure queue guard.
        m.start({"action": "import_drive"}, "admin")
        with patch.object(model_training, "_table", return_value=self.fake), \
             patch.object(model_training, "status",
                          return_value={"can_start": True, "base": "initial"}):
            with self.assertRaises(model_training.TrainingBlocked):
                model_training.start({"profile": "top-7.2.1"}, "admin")
        self.assertNotIn(
            (model_training.PARTITION, "request-initial"), self.fake.data
        )

    def test_factory_training_still_uses_original_protected_queue(self):
        with patch.object(model_training, "_table", return_value=self.fake), \
             patch.object(model_training, "status",
                          return_value={"can_start": True, "base": "initial"}):
            result = model_training.start({"profile": "top-7.2.1"}, "admin")
        self.assertEqual(result["state"], "QUEUED")
        row = self.fake.data[(model_training.PARTITION, "request-initial")]
        self.assertEqual(row["profile"], "top-7.2.1")
        self.assertIsNone(m._json("active"))

    def test_unknown_operations_and_fields_rejected(self):
        for data in (
            {"action": "promote"}, {"action": "refresh_tests", "max_requests": 100},
            {"action": "import_drive", "source_tag": "anything"},
            {"action": "activate_shadow", "source_tag": "../evil"},
            {"action": "activate_shadow", "source_tag": "blinq-candidate-frozen-000-1"},
            {"action": "train", "profile": "top-7.2.1"},
        ):
            with self.assertRaises(ValueError):
                m.start(data, "admin")
        self.assertIsNone(m._json("active"))

    def test_only_listed_frozen_candidate_is_accepted(self):
        queued = m.start({"action": "activate_shadow",
                          "source_tag": "blinq-candidate-frozen-123-1"}, "admin")
        active = m._json("active")
        self.assertEqual(active["source_sha256"], "c" * 64)
        self.assertEqual(active["expected_candidate_sha256"], "a" * 64)
        self.assertEqual(active["expected_champion_sha256"], "b" * 64)
        self.assertEqual(active["id"], queued["id"])

    def test_busy_and_stale_snapshot_block(self):
        old = snapshot()
        old["observed_at"] = "2020-01-01T00:00:00+00:00"
        m._put("snapshot", old)
        with self.assertRaises(model_training.TrainingBlocked):
            m.start({"action": "refresh_tests"}, "admin")
        old = snapshot()
        old["can_start"] = False
        m._put("snapshot", old)
        with self.assertRaises(model_training.TrainingBlocked):
            m.start({"action": "refresh_tests"}, "admin")

    def test_signed_sync_claims_once_and_waits_for_verified_completion(self):
        m.start({"action": "activate_shadow",
                 "source_tag": "blinq-candidate-frozen-123-1"}, "admin")
        first = m.sync(snapshot())
        self.assertEqual(first["pending"]["action"], "activate_shadow")
        self.assertIsNone(m.sync(snapshot())["pending"])
        request = m._json("active")
        running = snapshot()
        running["can_start"] = False
        running["runs"]["activate_shadow"] = [{
            "id": 51, "status": "in_progress", "conclusion": None,
            "display_title": "Model Lab activate shadow " + request["id"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "html_url": "https://github.com/BackstageTalks/tbt/actions/runs/51",
        }]
        self.assertIsNone(m.sync(running)["pending"])
        self.assertIsNotNone(m._json("active"))
        running["runs"]["activate_shadow"][0].update(status="completed", conclusion="success")
        running["active_sha256"] = "c" * 64
        self.assertIsNone(m.sync(running)["pending"])
        self.assertIsNone(m._json("active"))
        self.assertEqual(m._json("last")["state"], "WORKFLOW_VERIFIED")
        self.assertEqual(m._json("last")["action"], "activate_shadow")

    def test_candidate_checksum_mismatch_blocks_and_keeps_guard(self):
        m.start({"action": "activate_shadow",
                 "source_tag": "blinq-candidate-frozen-123-1"}, "admin")
        m.sync(snapshot())
        request = m._json("active")
        final = snapshot()
        final["can_start"] = False
        final["runs"]["activate_shadow"] = [{
            "id": 52, "status": "completed", "conclusion": "success",
            "display_title": "Model Lab activate shadow " + request["id"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }]
        with self.assertRaises(model_training.TrainingBlocked):
            m.sync(final)
        self.assertIsNotNone(m._json("active"))
        self.assertIsNone(m._json("last"))

    def test_failed_readonly_job_needs_explicit_acknowledgement(self):
        m.start({"action": "refresh_tests"}, "admin")
        m.sync(snapshot())
        request = m._json("active")
        complete = snapshot()
        complete["can_start"] = False
        complete["runs"]["refresh_tests"] = [{
            "id": 53, "status": "completed", "conclusion": "failure",
            "display_title": "Model Lab tests " + request["id"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }]
        m.sync(complete)
        self.assertEqual(m._json("last")["state"], "FAILED_NEEDS_REVIEW")
        self.assertIsNotNone(m._json("active"))
        with self.assertRaises(model_training.TrainingBlocked):
            m.acknowledge_failed({"action": "acknowledge_failed", "id": "wrong"})
        self.assertEqual(m.acknowledge_failed({"action": "acknowledge_failed", "id": request["id"]})["state"],
                         "FAILED_ACKNOWLEDGED")
        self.assertIsNone(m._json("active"))

    def test_failed_shadow_audit_is_readonly_and_can_be_acknowledged(self):
        m.start({"action": "audit_shadow"}, "admin")
        m.sync(snapshot())
        request = m._json("active")
        complete = snapshot()
        complete["can_start"] = False
        complete["runs"]["audit_shadow"] = [{
            "id": 79, "status": "completed", "conclusion": "failure",
            "display_title": "Model Lab audit " + request["id"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }]
        m.sync(complete)
        self.assertEqual(m._json("last")["state"], "FAILED_NEEDS_REVIEW")
        with self.assertRaises(model_training.TrainingBlocked):
            m.acknowledge_failed({"action": "acknowledge_failed", "id": "invalid"})
        result = m.acknowledge_failed({"action": "acknowledge_failed",
                                       "id": request["id"]})
        self.assertEqual(result["state"], "FAILED_ACKNOWLEDGED")
        self.assertIsNone(m._json("active"))

    def test_failed_shadow_activation_stays_locked(self):
        m.start({"action": "activate_shadow",
                 "source_tag": "blinq-candidate-frozen-123-1"}, "admin")
        m.sync(snapshot())
        request = m._json("active")
        complete = snapshot()
        complete["can_start"] = False
        complete["runs"]["activate_shadow"] = [{
            "id": 80, "status": "completed", "conclusion": "failure",
            "display_title": "Model Lab activate shadow " + request["id"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }]
        m.sync(complete)
        with self.assertRaises(model_training.TrainingBlocked):
            m.acknowledge_failed({"action": "acknowledge_failed", "id": request["id"]})
        self.assertIsNotNone(m._json("active"))

    def test_failed_import_cannot_be_unblocked_from_admin(self):
        m.start({"action": "import_drive"}, "admin")
        m.sync(snapshot())
        request = m._json("active")
        complete = snapshot()
        complete["can_start"] = False
        complete["runs"]["import_drive"] = [{
            "id": 77, "status": "completed", "conclusion": "failure",
            "display_title": "CDB guarded import " + request["id"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }]
        m.sync(complete)
        with self.assertRaises(model_training.TrainingBlocked):
            m.acknowledge_failed({"action": "acknowledge_failed", "id": request["id"]})
        self.assertIsNotNone(m._json("active"))

    def test_wrong_champion_never_unblocks_shadow(self):
        m.start({"action": "activate_shadow",
                 "source_tag": "blinq-candidate-frozen-123-1"}, "admin")
        m.sync(snapshot())
        request = m._json("active")
        complete = snapshot()
        complete["can_start"] = False
        complete["active_sha256"] = "c" * 64
        complete["champion_sha256"] = "d" * 64
        complete["runs"]["activate_shadow"] = [{
            "id": 54, "status": "completed", "conclusion": "success",
            "display_title": "Model Lab activate shadow " + request["id"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }]
        with self.assertRaises(model_training.TrainingBlocked):
            m.sync(complete)
        self.assertIsNotNone(m._json("active"))

    def test_status_does_not_present_queue_as_finished(self):
        m.start({"action": "refresh_tests"}, "admin")
        result = m.status()
        self.assertFalse(result["can_start"])
        self.assertEqual(result["operation"]["state"], "QUEUED")


class TestLiveAdminProbe(unittest.TestCase):
    def setUp(self):
        import os
        p = patch.dict(os.environ, {"BLINQ_BASE_URL": "https://agreeable-sky-011a7fe10.7.azurestaticapps.net"})
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def endpoint_status(code, body=b''):
        def fake(request, timeout):
            assert request.full_url == (
                "https://agreeable-sky-011a7fe10.7.azurestaticapps.net/api/v1/admin/model-lab")
            assert request.get_method() == "GET"
            raise HTTPError(request.full_url, code, "test", {}, io.BytesIO(body))
        return fake

    def test_404_waits_without_any_signed_model_write(self):
        from admin_model_lab_worker import admin_model_lab_endpoint_ready, main
        self.assertFalse(admin_model_lab_endpoint_ready(
            open_url=self.endpoint_status(404)))
        with patch("admin_model_lab_worker.admin_model_lab_endpoint_ready", return_value=False), \
             patch("admin_model_lab_worker.collect_status") as collect, \
             patch("admin_model_lab_worker.sync") as sync:
            main()
            collect.assert_not_called()
            sync.assert_not_called()

    def test_only_exact_protected_json_401_proves_live_endpoint(self):
        from admin_model_lab_worker import admin_model_lab_endpoint_ready
        self.assertTrue(admin_model_lab_endpoint_ready(
            open_url=self.endpoint_status(401, b'{"error":"unauthorized"}')))
        for code, body in ((401, b'{"error":"something-else"}'),
                           (401, b'not-json'),
                           (403, b'{"error":"forbidden"}'),
                           (503, b'{"error":"storage-unavailable"}')):
            with self.subTest(code=code, body=body):
                with self.assertRaises(RuntimeError):
                    admin_model_lab_endpoint_ready(open_url=self.endpoint_status(code, body))

    def test_unauthenticated_success_never_proves_admin_protection(self):
        from admin_model_lab_worker import admin_model_lab_endpoint_ready
        class SuccessfulResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False
        with self.assertRaises(RuntimeError):
            admin_model_lab_endpoint_ready(open_url=lambda request, timeout: SuccessfulResponse())

    def test_wrong_publication_target_is_rejected(self):
        from admin_model_lab_worker import admin_model_lab_endpoint_ready
        with self.assertRaises(RuntimeError):
            admin_model_lab_endpoint_ready(base_url="http://localhost:7071",
                                            open_url=self.endpoint_status(401, b'{"error":"unauthorized"}'))



class TestWorker(unittest.TestCase):
    def test_import_has_hard_one_batch_cap_and_no_training_promotion(self):
        from admin_model_lab_worker import dispatch
        pending = {"action": "import_drive", "id": "a" * 24,
                   "expected_candidate_sha256": "a" * 64,
                   "expected_champion_sha256": "b" * 64}
        good = snapshot()
        with patch("admin_model_lab_worker.collect_status", return_value=good), \
             patch("admin_model_lab_worker.inspect", return_value={"can_start": True}), \
             patch("admin_model_lab_worker.training_status", return_value={"can_start": True}), \
             patch("admin_model_lab_worker.github") as gh:
            dispatch(pending)
            arguments = gh.call_args.args[1]
            self.assertEqual(arguments["inputs"]["catchup_remaining"], "0")
            self.assertEqual(arguments["inputs"]["request_id"], "a" * 24)
            self.assertNotIn("promote", json.dumps(arguments))
            self.assertNotIn("max_requests", json.dumps(arguments))

    def test_worker_refuses_candidate_change(self):
        from admin_model_lab_worker import dispatch
        pending = {"action": "refresh_tests", "id": "b" * 24,
                   "expected_candidate_sha256": "0" * 64,
                   "expected_champion_sha256": "b" * 64}
        with patch("admin_model_lab_worker.collect_status", return_value=snapshot()), \
             patch("admin_model_lab_worker.inspect", return_value={"can_start": True}), \
             patch("admin_model_lab_worker.training_status", return_value={"can_start": True}), \
             patch("admin_model_lab_worker.github") as gh:
            with self.assertRaises(model_training.TrainingBlocked):
                dispatch(pending)
            gh.assert_not_called()


class TestWorkerHeartbeat(unittest.TestCase):
    def test_existing_worker_follows_external_match_clock_without_git_cron(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / ".github/workflows/admin-training-worker.yml"
        source = path.read_text(encoding="utf-8")
        self.assertNotIn("\n  schedule:", source)
        self.assertIn("workflow_run:", source)
        self.assertIn("Prediction fixture schedule and match status", source)
        self.assertIn("Tennis data and predictions", source)
        self.assertIn("github.event.workflow_run.conclusion != 'skipped'", source)
        self.assertIn("cancel-in-progress: false", source)
        self.assertIn("python scripts/admin_training_worker.py", source)
        self.assertIn("python scripts/admin_model_lab_worker.py", source)
        self.assertNotIn("RAPIDAPI_KEY", source)


if __name__ == "__main__":
    unittest.main()
