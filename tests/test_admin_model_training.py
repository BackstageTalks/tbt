import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from tbt.services import model_training as m
from tbt.services import model_lab


class TrainingTests(unittest.TestCase):
    def setUp(self):
        # Queue tests operate against fake Admin storage; the cross-queue
        # guard is mocked unless a case explicitly simulates Lab contention.
        active = patch.object(model_lab, "_row", return_value=None)
        active.start()
        self.addCleanup(active.stop)

    def test_model_factory_active_operation_blocks_training(self):
        with patch.object(model_lab, "_row", return_value={"id": "busy"}), \
             patch.object(m, "status", return_value={"can_start": True, "base": "7"}), \
             patch.object(m, "_table") as table:
            with self.assertRaises(m.TrainingBlocked):
                m.start({"profile": "top-7.2.1"}, "admin")
            table.assert_not_called()

    def test_busy_blocks_before_claim(self):
        with patch.object(m, "status", return_value={"can_start": False, "reason": "busy"}), patch.object(m, "_table") as table:
            with self.assertRaises(m.TrainingBlocked): m.start({}, "admin")
            table.assert_not_called()

    def test_duplicate_or_storage_failure_blocks(self):
        with patch.object(m, "status", return_value={"can_start": True, "base": "7"}), patch.object(m, "_table") as table:
            table.return_value.create_entity.side_effect = RuntimeError("exists")
            with self.assertRaises(m.TrainingBlocked): m.start({}, "admin")

    def test_shadow_opt_in_rejects_invalid_profiles_or_types(self):
        for payload in ({"profile": "standard", "auto_shadow": True},
                        {"profile": "top-7.2.1", "auto_shadow": "true"}):
            with self.assertRaises(ValueError):
                m.start(payload, "admin")

    def test_client_cannot_choose_repository_or_promote(self):
        for payload in ({"repository": "other"}, {"promote": True}, {"profile": "unknown"}):
            with self.assertRaises(ValueError): m.start(payload, "admin")

    def test_start_only_queues_never_calls_github(self):
        with patch.object(m, "status", return_value={"can_start": True, "base": "7"}), patch.object(m, "_table") as table, patch.object(m, "github") as gh:
            self.assertEqual(m.start({"profile": "standard"}, "admin")["state"], "QUEUED")
            self.assertEqual(table.return_value.create_entity.call_args.args[0]["profile"], "standard")
            gh.assert_not_called()

    def test_722_profile_is_durably_queued_without_production_write(self):
        with patch.object(m, "status", return_value={"can_start": True, "base": "8"}), patch.object(m, "_table") as table, patch.object(m, "github") as gh:
            self.assertEqual(m.start({"profile": "accuracy-7.2.2"}, "admin")["state"], "QUEUED")
            self.assertEqual(table.return_value.create_entity.call_args.args[0]["profile"], "accuracy-7.2.2")
            gh.assert_not_called()

    def test_722_shadow_requires_verified_preflight(self):
        with patch.object(model_lab, "_json", return_value=None), patch.object(m, "_table") as table:
            with self.assertRaises(m.TrainingBlocked):
                m.start({"profile": "accuracy-7.2.2", "auto_shadow": True}, "admin")
            table.assert_not_called()

    def test_claim_is_returned_only_once(self):
        import json
        records = {"request-7": {"base": "7", "profile": "standard"}}
        def save(key, payload): records[key] = {"payload": json.dumps(payload)}
        def create(entity):
            key = entity["RowKey"]
            if key in records: raise RuntimeError("exists")
            records[key] = entity
        with patch.object(m, "save", side_effect=save), patch.object(m, "row", side_effect=records.get), patch.object(m, "_table") as table:
            table.return_value.create_entity.side_effect = create
            payload = {"snapshot": {"base": "7", "can_start": True}, "claim": True}
            self.assertEqual(m.sync(payload)["pending"]["profile"], "standard")
            self.assertIsNone(m.sync(payload)["pending"])

    def test_lock_change_cannot_look_free(self):
        refs = iter([None, {"object": {"sha": "a"}}])
        def read(path, **kwargs):
            if "git/ref" in path:
                return next(refs)
            return {"workflow_runs": []}
        self.assertFalse(m.inspect(read)["can_start"])

    def test_route_rejects_unauthorized_before_service_call(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "api/function_app.py").read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "admin_model_training")
        fn.decorator_list = []
        env = {"_admin_user": lambda req: (None, "denied")}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "endpoint", "exec"), env)
        with patch.object(m, "status") as status, patch.object(m, "start") as start:
            self.assertEqual(env[fn.name](Mock(method="POST")), "denied")
            status.assert_not_called()
            start.assert_not_called()
