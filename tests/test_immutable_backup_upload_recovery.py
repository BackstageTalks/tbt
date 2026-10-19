"""Regression coverage for partial immutable backup uploads (7.2.1)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import guarded_candidate_backup as backup


def fixture_backup(tmp_path, monkeypatch, *, fail_first=True, bad_size=False,
                   permanent=False, transient=False):
    stage = tmp_path / "staging"
    stage.mkdir()
    rows = []
    for i in range(3):
        name = f"frozen__history__history-202{i}.parquet"
        (stage / name).write_bytes(b"x" * (i + 2))
        rows.append({"asset": name, "bytes": i + 2})
    (stage / backup.ASSET_MANIFEST).write_text('{"schema":1}')
    remote, calls, attempts = {}, [], {}
    def fake_run(*args):
        if args[:3] == ("gh", "release", "view"):
            return json.dumps({"assets": [{"name": n, "size": v} for n, v in remote.items()]})
        assert args[:3] == ("gh", "release", "upload")
        assert "--clobber" not in args
        names = [Path(s).name for s in args[4:-2]]
        calls.append(names)
        if permanent:
            raise RuntimeError("HTTP 403 Resource not accessible by integration")
        if fail_first and len(names) > 1:
            remote[names[0]] = (stage / names[0]).stat().st_size + (1 if bad_size else 0)
            raise RuntimeError("HTTP 502 after partial upload")
        for name in names:
            if transient and name == rows[1]["asset"]:
                attempts[name] = attempts.get(name, 0) + 1
                if attempts[name] == 1:
                    raise RuntimeError("HTTP 503")
            assert name not in remote, "attempted overwrite"
            remote[name] = (stage / name).stat().st_size
        return ""
    monkeypatch.setattr(backup, "run", fake_run)
    monkeypatch.setattr(backup.time, "sleep", lambda seconds: None)
    return stage, rows, remote, calls


def test_partial_batch_reconciles_and_manifest_is_last(tmp_path, monkeypatch):
    stage, rows, remote, calls = fixture_backup(tmp_path, monkeypatch)
    backup.upload_immutable_backup("run-1", rows, stage)
    assert set(remote) == {r["asset"] for r in rows} | {backup.ASSET_MANIFEST}
    assert calls[0] == [r["asset"] for r in rows]
    assert calls[-1] == [backup.ASSET_MANIFEST]
    assert sum(rows[0]["asset"] in batch for batch in calls) == 1


def test_transient_retries_missing_asset(tmp_path, monkeypatch):
    stage, rows, remote, calls = fixture_backup(tmp_path, monkeypatch, transient=True)
    backup.upload_immutable_backup("run-1", rows, stage)
    assert backup.ASSET_MANIFEST in remote
    assert sum(rows[1]["asset"] in batch for batch in calls) == 3


def test_existing_different_size_fails_without_manifest(tmp_path, monkeypatch):
    stage, rows, remote, calls = fixture_backup(tmp_path, monkeypatch, bad_size=True)
    with pytest.raises(RuntimeError, match="refusing overwrite"):
        backup.upload_immutable_backup("run-1", rows, stage)
    assert backup.ASSET_MANIFEST not in remote


def test_auth_error_fails_closed_without_manifest(tmp_path, monkeypatch):
    stage, rows, remote, calls = fixture_backup(
        tmp_path, monkeypatch, permanent=True, fail_first=False)
    with pytest.raises(RuntimeError, match="HTTP 403"):
        backup.upload_immutable_backup("run-1", rows, stage)
    assert backup.ASSET_MANIFEST not in remote


def test_cli_error_is_visible(monkeypatch):
    monkeypatch.setattr(
        backup.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="HTTP 502 upload rejected"),
    )
    with pytest.raises(RuntimeError, match="HTTP 502"):
        backup.run("gh", "release", "upload", "tag")
