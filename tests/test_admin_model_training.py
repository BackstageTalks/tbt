import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from tbt.services import model_training as m


class TrainingTests(unittest.TestCase):
    def test_busy_blocks_before_claim_or_dispatch(self):
        with patch.object(m, "inspect", return_value={"can_start": False, "reason": "busy"}), patch.object(m, "github") as gh, patch.object(m, "_table") as table:
            with self.assertRaises(m.TrainingBlocked):
                m.start({}, "admin")
            gh.assert_not_called()
            table.assert_not_called()

    def test_duplicate_or_unavailable_storage_never_dispatches(self):
        with patch.object(m, "inspect", return_value={"can_start": True, "base": "7"}), patch.object(m, "github", return_value={"sha": "a"}) as gh, patch.object(m, "_table") as table:
            table.return_value.create_entity.side_effect = RuntimeError("already exists")
            with self.assertRaises(m.TrainingBlocked):
                m.start({}, "admin")
            self.assertEqual(gh.call_count, 1)

    def test_unknown_dispatch_retains_claim(self):
        with patch.object(m, "inspect", return_value={"can_start": True, "base": "7"}), patch.object(m, "github", side_effect=[{"sha": "a"}, m.TrainingUnavailable("timeout")]), patch.object(m, "_table") as table:
            with self.assertRaises(m.TrainingUnavailable):
                m.start({}, "admin")
            table.return_value.create_entity.assert_called_once()
            table.return_value.delete_entity.assert_not_called()

    def test_client_cannot_choose_repository_or_promote(self):
        for payload in ({"repository": "other"}, {"promote": True}, {"profile": "unknown"}):
            with self.assertRaises(ValueError):
                m.start(payload, "admin")

    def test_start_uses_fixed_workflow_main_and_selected_profile(self):
        with patch.object(m, "inspect", return_value={"can_start": True, "base": "7"}), patch.object(m, "github", return_value={"sha": "a"}) as gh, patch.object(m, "_table"):
            self.assertEqual(m.start({"profile": "standard"}, "admin")["state"], "DISPATCHED_NOT_VERIFIED")
            self.assertEqual(gh.call_args.args[1], {"ref": "main", "inputs": {"training_profile": "standard"}})

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
