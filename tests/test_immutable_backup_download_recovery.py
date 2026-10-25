"""Remote rollback readback must survive 504s without trusting partial bytes."""
from pathlib import Path

import pytest

from scripts import guarded_candidate_backup as backup


def setup_readback(tmp_path, monkeypatch, failures=(), corrupt=False, missing=False):
    stage, restore = tmp_path / "stage", tmp_path / "restore"
    stage.mkdir()
    restore.mkdir()
    name = "frozen__production__model.joblib"
    payload = b"complete model bytes"
    (stage / name).write_bytes(payload)
    manifest = stage / backup.ASSET_MANIFEST
    manifest.write_bytes(b'{"schema": 1}')
    rows = [{"asset": name, "bytes": len(payload), "sha256": backup.sha(stage / name)}]
    calls, delays = [], []

    def remote_download(*args):
        assert args[:3] == ("gh", "release", "download")
        assert "--clobber" not in args
        asset = args[args.index("--pattern") + 1]
        directory = Path(args[args.index("-D") + 1])
        assert not list(directory.iterdir()), "attempt reused partial download"
        calls.append((asset, directory))
        destination = directory / asset
        if asset == name and len(calls) <= len(failures):
            destination.write_bytes(b"partial")
            raise RuntimeError(failures[len(calls) - 1])
        if not missing:
            destination.write_bytes(b"x" * len(payload) if corrupt else (stage / asset).read_bytes())
        return ""

    monkeypatch.setattr(backup, "run", remote_download)
    monkeypatch.setattr(backup.time, "sleep", delays.append)
    return stage, restore, rows, calls, delays


def test_partial_504_retries_in_fresh_directory_then_verifies_manifest(tmp_path, monkeypatch):
    stage, restore, rows, calls, delays = setup_readback(
        tmp_path, monkeypatch, failures=["HTTP 504 Gateway Timeout", "unexpected EOF"])
    backup.download_immutable_backup("tag", rows, stage, restore)
    assert delays == [2, 4]
    assert len(calls) == 4
    assert len({directory for _, directory in calls}) == 4
    for name in [rows[0]["asset"], backup.ASSET_MANIFEST]:
        assert backup.sha(restore / name) == backup.sha(stage / name)
    assert all(not directory.exists() for _, directory in calls)


@pytest.mark.parametrize("error", ["HTTP 403 Forbidden", "HTTP 404 Not Found"])
def test_permanent_failure_never_retries_or_accepts_partial(tmp_path, monkeypatch, error):
    stage, restore, rows, calls, delays = setup_readback(tmp_path, monkeypatch, [error])
    with pytest.raises(RuntimeError, match=error):
        backup.download_immutable_backup("tag", rows, stage, restore)
    assert len(calls) == 1
    assert not delays
    assert not list(restore.iterdir())


def test_transient_failure_has_bounded_retries(tmp_path, monkeypatch):
    stage, restore, rows, calls, delays = setup_readback(tmp_path, monkeypatch, ["HTTP 504"] * 5)
    with pytest.raises(RuntimeError, match="HTTP 504"):
        backup.download_immutable_backup("tag", rows, stage, restore)
    assert len(calls) == 5
    assert delays == [2, 4, 8, 16]
    assert not list(restore.iterdir())


@pytest.mark.parametrize("mode", ["corrupt", "missing"])
def test_successful_cli_with_bad_bytes_fails_closed(tmp_path, monkeypatch, mode):
    stage, restore, rows, calls, delays = setup_readback(tmp_path, monkeypatch, **{mode: True})
    with pytest.raises(RuntimeError, match="SHA mismatch"):
        backup.download_immutable_backup("tag", rows, stage, restore)
    assert len(calls) == 1
    assert not delays
    assert not list(restore.iterdir())


def test_existing_local_bytes_cannot_replace_remote_readback(tmp_path, monkeypatch):
    stage, restore, rows, calls, _ = setup_readback(tmp_path, monkeypatch)
    (restore / rows[0]["asset"]).write_bytes((stage / rows[0]["asset"]).read_bytes())
    with pytest.raises(RuntimeError, match="must start empty"):
        backup.download_immutable_backup("tag", rows, stage, restore)
    assert not calls


@pytest.mark.parametrize("asset", ["../model", "*", ".", ".."])
def test_unsafe_asset_names_rejected_before_download(tmp_path, monkeypatch, asset):
    stage, restore, rows, calls, _ = setup_readback(tmp_path, monkeypatch)
    rows[0]["asset"] = asset
    with pytest.raises(RuntimeError, match="unsafe"):
        backup.download_immutable_backup("tag", rows, stage, restore)
    assert not calls
