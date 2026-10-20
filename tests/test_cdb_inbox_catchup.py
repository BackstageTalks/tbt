"""No-network safety tests for bounded, verified CDB Drive catch-up chains."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import cdb_inbox_catchup as c


def valid_report(pending=1250, fetched=100):
    return {"schema": 2, "state": "DRIVE_SOURCE_FETCH_ONLY",
            "production_mutated": False, "api_requests": 0,
            "pending_supported": pending, "fetched": fetched}


@pytest.mark.parametrize("remaining,expected", [(0, None), (1, 0), (4, 3), (6, 5)])
def test_bounded_decreasing_budget(remaining, expected):
    assert c.next_budget(remaining, valid_report()) == expected


@pytest.mark.parametrize("pending,fetched", [(0, 100), (20, 0), (0, 0)])
def test_completed_or_no_progress_never_loops(pending, fetched):
    assert c.next_budget(6, valid_report(pending, fetched)) is None


@pytest.mark.parametrize("count", [-1, 7, 10**8, True])
def test_bad_budget_fails_closed(count):
    with pytest.raises(c.CatchupBlocked):
        c.next_budget(count, valid_report())


@pytest.mark.parametrize("change", [
    {"schema": 999},
    {"state": "PRODUCTION_MUTATED"},
    {"production_mutated": True},
    {"api_requests": 1},
    {"pending_supported": -1},
    {"pending_supported": None},
    {"fetched": 101},
    {"fetched": "100"},
])
def test_untrusted_source_never_triggers(change):
    m = valid_report()
    m.update(change)
    with pytest.raises(c.CatchupBlocked):
        c.next_budget(2, m)


def test_one_catchup_dispatch_uses_actions_token_not_private(monkeypatch, tmp_path):
    for key, value in {
        "GITHUB_REPOSITORY": "BackstageTalks/tbt",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "ACTIONS_DISPATCH_TOKEN": "actions-only",
        "GH_TOKEN": "private-CDB-token",
    }.items():
        monkeypatch.setenv(key, value)
    manifest = tmp_path / "drive_manifest.json"
    manifest.write_text(json.dumps(valid_report()))
    runner = Mock(return_value=SimpleNamespace(returncode=0))
    assert c.queue_next(3, manifest_path=manifest, runner=runner)
    runner.assert_called_once()
    args, kwargs = runner.call_args
    assert args[0] == ["gh", "workflow", "run", "cdb-drive-inbox.yml",
                       "--repo", "BackstageTalks/tbt", "--ref", "main",
                       "-f", "catchup_remaining=2"]
    assert kwargs["check"]
    assert kwargs["env"]["GH_TOKEN"] == "actions-only"
    assert monkeypatch is not None


def test_no_source_manifest_is_safe_stop_not_false_progress(monkeypatch, tmp_path):
    for key, value in {
        "GITHUB_REPOSITORY": "BackstageTalks/tbt",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "ACTIONS_DISPATCH_TOKEN": "token",
    }.items():
        monkeypatch.setenv(key, value)
    runner = Mock()
    assert not c.queue_next(3, manifest_path=tmp_path / "missing.json", runner=runner)
    runner.assert_not_called()


@pytest.mark.parametrize("key,bad", [
    ("GITHUB_REPOSITORY", "other/repo"),
    ("GITHUB_REF", "refs/heads/feature"),
    ("GITHUB_EVENT_NAME", "pull_request"),
    ("ACTIONS_DISPATCH_TOKEN", ""),
])
def test_not_main_or_no_token_is_blocked(monkeypatch, tmp_path, key, bad):
    for k, v in {
        "GITHUB_REPOSITORY": "BackstageTalks/tbt",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "ACTIONS_DISPATCH_TOKEN": "token",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv(key, bad)
    manifest = tmp_path / "drive_manifest.json"
    manifest.write_text(json.dumps(valid_report()))
    with pytest.raises(c.CatchupBlocked):
        c.queue_next(2, manifest_path=manifest, runner=Mock())


def test_dispatch_failure_is_error_not_reported_as_success(monkeypatch, tmp_path):
    for k, v in {
        "GITHUB_REPOSITORY": "BackstageTalks/tbt",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "ACTIONS_DISPATCH_TOKEN": "token",
    }.items():
        monkeypatch.setenv(k, v)
    manifest = tmp_path / "drive_manifest.json"
    manifest.write_text(json.dumps(valid_report()))
    with pytest.raises(RuntimeError, match="network"):
        c.queue_next(1, manifest_path=manifest, runner=Mock(side_effect=RuntimeError("network")))


def test_workflow_dispatch_chains_only_after_progress_and_writer_release():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/cdb-drive-inbox.yml").read_text()
    operator = (root / ".github/workflows/cdb-import-operator-dispatch.yml").read_text()
    assert "catchup_remaining:" in workflow
    assert "type: number" in workflow
    assert "python scripts/cdb_inbox_catchup.py --remaining" in workflow
    assert workflow.index("Clear PRIVATE prepared batch only after checkpoint readback") < workflow.index("Chain a bounded next")
    assert workflow.index("Always release global writer if owned") < workflow.index("Chain a bounded next")
    assert "steps.prepared.outputs.restored != 'true'" in workflow
    assert "steps.writer.outputs.locked == 'true'" in workflow
    assert "gh workflow run cdb-drive-inbox.yml" in operator
    assert "-f catchup_remaining=4" in operator
    assert "\\n  schedule:" not in workflow
