"""Incident regressions: no GitHub 5xx can silently drop a CDB asset."""
import hashlib
from pathlib import Path

import pytest

from release_store import ReleaseStore


def make_store(tmp_path, *, existing=(), fail_upload=None, fail_rename=None):
    store = object.__new__(ReleaseStore)
    store.repository = "BackstageTalks/tbt-data"
    store.tag = "tbt-data-v1"
    store.directory = tmp_path
    data = {}
    next_id = [100]

    def create(name, content):
        next_id[0] += 1
        data[name] = {
            "id": next_id[0], "name": name, "state": "uploaded",
            "size": len(content), "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            "body": content,
        }

    for name in existing:
        create(name, b"previous verified content: " + name.encode())

    def inventory():
        return {name: asset.copy() for name, asset in data.items()}

    def upload(paths):
        for path in paths:
            path = Path(path)
            if fail_upload is not None and fail_upload(path.name):
                raise RuntimeError("GitHub CLI operation failed: HTTP 500")
            create(path.name, path.read_bytes())

    def api(method, asset_id, *, name=None):
        item = next((a for a in data.values() if a["id"] == asset_id), None)
        if item is None:
            raise RuntimeError("asset id not found")
        if method == "DELETE":
            del data[item["name"]]
            return ""
        if method == "PATCH":
            if fail_rename is not None and fail_rename(item["name"], name):
                raise RuntimeError("GitHub CLI operation failed: HTTP 500")
            if name in data:
                raise RuntimeError("GitHub release asset name collision")
            del data[item["name"]]
            item["name"] = name
            data[name] = item
            return ""
        raise AssertionError(method)

    store._release_asset_inventory = inventory
    store._remote_bundle_files = lambda: {}
    store._asset_names = lambda: set(data)
    store.upload = upload
    store._asset_api = api
    return store, data


def write_payloads(tmp_path):
    parquet = tmp_path / "history-2026.parquet"
    parquet.write_bytes(b"new year data with validated canonical identities")
    history = tmp_path / "history_manifest.json"
    history.write_text('{"years": {"2026": {"asset": "history-2026.parquet"}}}')
    progress = tmp_path / "download_progress.json"
    progress.write_text('{"schema": 1, "completed_days": ["2026-10-30"]}')
    return [parquet, history, progress]


def test_successful_bundle_commit_preserves_new_bytes_and_cleans_backups(tmp_path):
    old = ("history-2026.parquet", "history_manifest.json",
           "download_progress.json", "_tbt_bundle_manifest.json")
    store, remote = make_store(tmp_path, existing=old)
    paths = write_payloads(tmp_path)
    store.upload_bundle(paths)
    assert set(remote) == set(old)
    for path in paths:
        assert remote[path.name]["body"] == path.read_bytes()
    assert store._verified_asset(store._release_asset_inventory(),
                                  "_tbt_bundle_manifest.json",
                                  tmp_path / "_tbt_bundle_manifest.json")


def test_failed_checksum_commit_restores_all_previous_canonical_assets(tmp_path):
    old = ("history-2026.parquet", "history_manifest.json",
           "download_progress.json", "_tbt_bundle_manifest.json")
    store, remote = make_store(
        tmp_path, existing=old,
        fail_upload=lambda name: name.startswith("blinq-candidate-")
        and name.endswith("_tbt_bundle_manifest.json"))
    originals = {name: remote[name]["body"] for name in old}
    with pytest.raises(RuntimeError, match="HTTP 500"):
        store.upload_bundle(write_payloads(tmp_path))
    assert all(remote[name]["body"] == payload for name, payload in originals.items())
    assert not any(name.startswith("blinq-rollback-") for name in remote)


def test_failed_manifest_rename_restores_canonical_and_never_deletes_old(tmp_path):
    store, remote = make_store(
        tmp_path, existing=("history_manifest.json",),
        fail_rename=lambda src, dst: src.startswith("blinq-candidate-")
        and dst == "history_manifest.json")
    original = remote["history_manifest.json"]["body"]
    history = tmp_path / "history_manifest.json"
    history.write_text('{"years": {}}')
    with pytest.raises(RuntimeError, match="HTTP 500"):
        store._guarded_publish(history, "0" * 32)
    assert remote["history_manifest.json"]["body"] == original
    assert not any(name.startswith("blinq-rollback-") for name in remote)


def test_failed_commit_removes_new_partitions_without_previous_copy(tmp_path):
    old = ("history_manifest.json", "_tbt_bundle_manifest.json")
    store, remote = make_store(
        tmp_path, existing=old,
        fail_upload=lambda name: name.startswith("blinq-candidate-")
        and name.endswith("_tbt_bundle_manifest.json"))
    originals = {name: remote[name]["body"] for name in old}
    with pytest.raises(RuntimeError, match="HTTP 500"):
        store.upload_bundle(write_payloads(tmp_path))
    assert "history-2026.parquet" not in remote
    assert "download_progress.json" not in remote
    assert all(remote[name]["body"] == payload for name, payload in originals.items())


def test_retention_removal_is_rolled_back_on_checksum_failure(tmp_path):
    old = ("history-2024.parquet", "history_manifest.json",
           "_tbt_bundle_manifest.json")
    store, remote = make_store(
        tmp_path, existing=old,
        fail_upload=lambda name: name.startswith("blinq-candidate-")
        and name.endswith("_tbt_bundle_manifest.json"))
    originals = {name: remote[name]["body"] for name in old}
    history = tmp_path / "history_manifest.json"
    history.write_text('{"years": {}}')
    with pytest.raises(RuntimeError, match="HTTP 500"):
        store.upload_bundle([history], remove_names=("history-2024.parquet",))
    assert all(remote[name]["body"] == payload for name, payload in originals.items())
