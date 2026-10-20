"""Offline regression tests: CDB writer contention must queue, never steal."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cdb_inbox_wait_and_resume as queue
from wait_for_cdb_writer_idle import GateBlocked


def test_busy_then_idle_keeps_waiting_until_safe():
    states = iter(["BUSY", "BUSY", "FREE"])
    sleep = Mock()
    assert queue.await_idle_or_defer(90, 30, inspect=lambda: next(states),
                                    clock=lambda: 0, sleep=sleep)
    assert sleep.call_count == 2


def test_live_contention_defers_after_bounded_lease():
    times = iter([0, 20, 40, 61])
    sleep = Mock()
    assert not queue.await_idle_or_defer(
        60, 20, inspect=lambda: "BUSY", clock=lambda: next(times), sleep=sleep
    )
    assert sleep.call_count == 2


def test_immediate_idle_does_not_sleep():
    sleep = Mock()
    assert queue.await_idle_or_defer(
        60, 10, inspect=lambda: "FREE", clock=lambda: 0, sleep=sleep
    )
    sleep.assert_not_called()


def test_invalid_status_and_stale_lock_fail_closed():
    with pytest.raises(GateBlocked, match="Unexpected"):
        queue.await_idle_or_defer(3, 1, inspect=lambda: "STALE", clock=lambda: 0)
    def stale():
        raise GateBlocked("finished but lock remains; manual owner-scoped recovery required")
    with pytest.raises(GateBlocked, match="manual owner-scoped recovery"):
        queue.await_idle_or_defer(3, 1, inspect=stale, clock=lambda: 0)


def test_dispatch_is_one_main_workflow_and_uses_only_actions_token(monkeypatch):
    for key, val in {
        "GITHUB_REPOSITORY": "BackstageTalks/tbt",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "ACTIONS_DISPATCH_TOKEN": "public-actions-token",
        "GH_TOKEN": "private-cdb-token",
    }.items():
        monkeypatch.setenv(key, val)
    runner = Mock(return_value=SimpleNamespace(returncode=0))
    queue.enqueue_next_attempt(runner=runner)
    runner.assert_called_once()
    args, kwargs = runner.call_args
    assert args[0] == ["gh", "workflow", "run", "cdb-drive-inbox.yml",
                       "--repo", "BackstageTalks/tbt", "--ref", "main"]
    assert kwargs["check"] is True
    assert kwargs["env"]["GH_TOKEN"] == "public-actions-token"
    assert os.environ["GH_TOKEN"] == "private-cdb-token"


@pytest.mark.parametrize("key,bad", [
    ("GITHUB_REPOSITORY", "another/repo"),
    ("GITHUB_REF", "refs/heads/untrusted"),
    ("GITHUB_EVENT_NAME", "pull_request"),
    ("ACTIONS_DISPATCH_TOKEN", ""),
])
def test_dispatch_rejects_untrusted_context(monkeypatch, key, bad):
    for k, v in {
        "GITHUB_REPOSITORY": "BackstageTalks/tbt",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "ACTIONS_DISPATCH_TOKEN": "token",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv(key, bad)
    with pytest.raises(GateBlocked):
        queue.enqueue_next_attempt(runner=Mock(side_effect=AssertionError("must not dispatch")))


def test_failed_dispatch_fails_closed(monkeypatch):
    for key, val in {
        "GITHUB_REPOSITORY": "BackstageTalks/tbt",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "ACTIONS_DISPATCH_TOKEN": "token",
    }.items():
        monkeypatch.setenv(key, val)
    with pytest.raises(RuntimeError, match="down"):
        queue.enqueue_next_attempt(runner=Mock(side_effect=RuntimeError("API down")))


def test_queue_output_is_a_boolean_and_requires_runner_output(tmp_path, monkeypatch):
    out = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    queue.write_output(ready=False)
    queue.write_output(ready=True)
    assert out.read_text() == "ready=false\\nready=true\\n".replace("\\n", "\n")
    monkeypatch.delenv("GITHUB_OUTPUT")
    with pytest.raises(GateBlocked, match="Missing GITHUB_OUTPUT"):
        queue.write_output(ready=False)


def test_legacy_dispatch_helper_remains_read_only_but_new_import_does_not_wait():
    workflow = (ROOT / ".github/workflows/cdb-drive-inbox.yml").read_text()
    assert "await-cdb-writer-idle:" not in workflow
    assert "Observe CDB writer only AFTER normalized data preparation" in workflow
    assert "steps.writer_gate.outputs.ready == 'true'" in workflow
    assert "steps.writer.outputs.locked == 'true'" in workflow
    assert "if: always()" in workflow
    assert "Always release global writer if owned" in workflow
    # The former long-duration waiter is retained solely for old training
    # flows and must not be called by the CDB inbox importer.
    assert "python scripts/cdb_inbox_wait_and_resume.py --max-seconds" not in workflow
    source = (ROOT / "scripts/cdb_inbox_wait_and_resume.py").read_text()
    assert '["gh", "workflow", "run", WORKFLOW' in source
    assert "git/refs/tags" not in source
    assert "release delete" not in source
