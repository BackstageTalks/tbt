"""Incident regressions: no GitHub 5xx can silently drop a CDB asset."""
import hashlib
from pathlib import Path

import pytest

from release_store import ReleaseStore


@pytest.fixture(autouse=True)
def _simulate_owned_global_writer_lock(monkeypatch):
    # CI itself is a GitHub Actions environment, so the production writer
    # correctly enforces its lock. Only this isolated in-memory unit fixture
    # substitutes lock ownership; the lock integration tests remain unchanged.
    import cdb_global_writer_lock
    monkeypatch.setattr(cdb_global_writer_lock, "verify", lambda *_args, **_kwargs: {})


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


def test_interrupted_commit_restores_previous_manifest_before_next_api_run(
    tmp_path, monkeypatch,
):
    import cdb_global_writer_lock
    import json

    monkeypatch.setattr(cdb_global_writer_lock, "verify", lambda *_args: None)
    store, remote = make_store(
        tmp_path, existing=("history_manifest.json", "_tbt_bundle_manifest.json"))
    old = remote["history_manifest.json"]["body"]
    token = "a" * 32
    history = tmp_path / "history_manifest.json"
    history.write_text('{"years": {"2026": {"asset": "history-2026.parquet"}}}')
    store._guarded_publish(history, token)
    assert remote["history_manifest.json"]["body"] != old
    journal = tmp_path / f"blinq-txn-{token}.json"
    journal.write_text(json.dumps({
        "schema": 1,
        "created": [],
        "target_bundle_sha256": "f" * 64,
    }))
    store.upload([journal])
    store._download_asset = lambda name: (store.directory / name).write_bytes(remote[name]["body"])
    store.download = lambda: (
        None if remote["history_manifest.json"]["body"] == old
        else (_ for _ in ()).throw(RuntimeError("uncommitted checksum"))
    )
    report = store.recover_interrupted_swaps()
    assert report["status"] == "previous_generation_restored"
    assert remote["history_manifest.json"]["body"] == old
    assert not any(n.startswith("blinq-rollback-") or n.startswith("blinq-txn-")
                   for n in remote)


def test_interrupted_cleanup_preserves_verified_new_bundle(tmp_path, monkeypatch):
    import cdb_global_writer_lock
    import json

    monkeypatch.setattr(cdb_global_writer_lock, "verify", lambda *_args: None)
    store, remote = make_store(
        tmp_path, existing=("history_manifest.json", "_tbt_bundle_manifest.json"))
    token = "b" * 32
    history = tmp_path / "history_manifest.json"
    history.write_text('{"years": {}}')
    store._guarded_publish(history, token)
    bundle = tmp_path / "_tbt_bundle_manifest.json"
    bundle.write_text('{"schema": 1, "files": {}}')
    store._guarded_publish(bundle, token)
    journal = tmp_path / f"blinq-txn-{token}.json"
    journal.write_text(json.dumps({
        "schema": 1, "created": [],
        "target_bundle_sha256": store._sha256(bundle),
    }))
    store.upload([journal])
    store._download_asset = lambda name: (store.directory / name).write_bytes(remote[name]["body"])
    store.download = lambda: None
    report = store.recover_interrupted_swaps()
    assert report["status"] == "committed_generation_verified"
    assert remote["_tbt_bundle_manifest.json"]["body"] == bundle.read_bytes()
    assert not any(n.startswith("blinq-rollback-") or n.startswith("blinq-txn-")
                   for n in remote)


def _prediction_orphans_fixture(tmp_path, *, corrupt_manifest=False):
    """Two orphaned tokens surrounding a valid current production bundle."""
    import json

    canonical = ("feed.json", "ledger.json", "daily_offer_snapshot.json",
                 "_tbt_bundle_manifest.json")
    store, remote = make_store(tmp_path, existing=canonical)
    store.tag = "tbt-predictions-v1"
    def put(name, content):
        path = tmp_path / name
        path.write_bytes(content)
        store.upload([path])

    manifest = {"schema": 1, "files": {
        name: {"sha256": remote[name]["digest"][7:],
               "bytes": remote[name]["size"]}
        for name in canonical if name != "_tbt_bundle_manifest.json"}}
    put("_tbt_bundle_manifest.json", json.dumps(manifest).encode())
    original_ids = {name: remote[name]["id"] for name in canonical}
    original_digests = {name: remote[name]["digest"] for name in canonical}
    for token in ("a" * 32, "b" * 32):
        put(f"blinq-txn-{token}.json", json.dumps({
            "schema": 1, "created": [],
            "target_bundle_sha256": "f" * 64,
        }).encode())
        put(f"blinq-rollback-{token}-daily_offer_snapshot.json",
            b"old preserved release asset")
    put(f"blinq-candidate-{'a' * 32}-daily_offer_snapshot.json",
        b"abandoned staged bytes")

    def fake_download(*, required_names=()):
        if corrupt_manifest:
            raise RuntimeError("Release bundle checksum mismatch")
        remote_manifest = json.loads(remote["_tbt_bundle_manifest.json"]["body"])
        for name in required_names:
            assert hashlib.sha256(remote[name]["body"]).hexdigest() == (
                remote_manifest["files"][name]["sha256"])
            assert len(remote[name]["body"]) == remote_manifest["files"][name]["bytes"]
        return list(required_names)

    store._download_asset = lambda name: (
        (store.directory / name).write_bytes(remote[name]["body"]))
    store.download = fake_download
    return store, remote, original_ids, original_digests


def test_multiple_prediction_orphans_cleaned_only_after_verified_bundle(tmp_path):
    store, remote, ids, digests = _prediction_orphans_fixture(tmp_path)
    report = store.recover_interrupted_swaps()
    assert report == {
        "pending_transactions": 2,
        "status": "committed_generation_verified",
        "orphan_assets_cleaned": 5,
    }
    assert all(remote[name]["id"] == ids[name] for name in ids)
    assert all(remote[name]["digest"] == digests[name] for name in digests)
    assert not any(name.startswith(("blinq-candidate-", "blinq-rollback-",
                                    "blinq-txn-")) for name in remote)
    assert store.recover_interrupted_swaps()["status"] == "clean"


def test_multiple_prediction_orphans_block_without_canonical_readback(tmp_path):
    store, remote, ids, _ = _prediction_orphans_fixture(
        tmp_path, corrupt_manifest=True)
    before = set(remote)
    with pytest.raises(RuntimeError, match="Multiple pending bundle swaps"):
        store.recover_interrupted_swaps()
    assert set(remote) == before
    assert all(remote[name]["id"] == ids[name] for name in ids)


def test_unrecognized_prediction_candidate_prevents_cleanup(tmp_path):
    store, remote, _, _ = _prediction_orphans_fixture(tmp_path)
    path = tmp_path / f"blinq-candidate-{'c' * 32}-feed.json"
    path.write_bytes(b"unknown transaction")
    store.upload([path])
    before = set(remote)
    with pytest.raises(RuntimeError, match="Unrecognized pending"):
        store.recover_interrupted_swaps()
    assert set(remote) == before


def test_single_stale_prediction_journal_does_not_rollback_verified_bundle(tmp_path):
    store, remote, ids, digests = _prediction_orphans_fixture(tmp_path)
    for name in list(remote):
        if ("b" * 32) in name:
            store._asset_api("DELETE", remote[name]["id"])
    report = store.recover_interrupted_swaps()
    assert report["status"] == "committed_generation_verified"
    assert report["pending_transactions"] == 1
    assert all(remote[name]["id"] == ids[name] for name in ids)
    assert all(remote[name]["digest"] == digests[name] for name in digests)
