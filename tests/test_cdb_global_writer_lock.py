"""No-network proofs for atomic cross-repository canonical CDB lock."""
import json

import pytest

from scripts import cdb_global_writer_lock as lock


def configure(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "BackstageTalks/tbt")
    monkeypatch.setenv("GITHUB_RUN_ID", "123456789")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    state = {"ref": None, "tag": None, "creates": 0}

    def fake_api(repo, endpoint, *, method="GET", data=None):
        assert repo == lock.DEFAULT_REPOSITORY
        if endpoint == "git/ref/heads/main":
            return {"object": {"sha": "a" * 40}}
        if endpoint == "git/tags" and method == "POST":
            state["tag"] = {"sha": "b" * 40, "message": data["message"]}
            return state["tag"]
        if endpoint == "git/refs" and method == "POST":
            state["creates"] += 1
            if state["ref"] is not None:
                raise RuntimeError("HTTP 422 Reference already exists")
            state["ref"] = data["sha"]
            return {"object": {"sha": state["ref"]}}
        if endpoint == lock.LOCK_GET:
            return {"object": {"sha": state["ref"]}} if state["ref"] else None
        if endpoint == "git/tags/" + "b" * 40:
            return state["tag"]
        if endpoint == "git/refs/tags/blinq-cdb-global-writer" and method == "DELETE":
            state["ref"] = None
            return {}
        raise AssertionError((method, endpoint))

    monkeypatch.setattr(lock, "_api", fake_api)
    return state


def test_only_owner_can_publish_and_release(monkeypatch, tmp_path):
    state = configure(monkeypatch)
    path = tmp_path / "lock.json"
    lock.acquire(lock.DEFAULT_REPOSITORY, path, wait_seconds=0)
    assert state["creates"] == 1
    assert lock.verify(lock.DEFAULT_REPOSITORY, path)["tag_sha"] == "b" * 40
    assert json.loads(path.read_text())["owner"].endswith("/123456789/attempts/1")
    monkeypatch.setenv("GITHUB_RUN_ID", "987")
    with pytest.raises(RuntimeError, match="different repository/run"):
        lock.verify(lock.DEFAULT_REPOSITORY, path)
    with pytest.raises(RuntimeError, match="different repository/run"):
        lock.release(lock.DEFAULT_REPOSITORY, path)
    assert state["ref"] is not None
    monkeypatch.setenv("GITHUB_RUN_ID", "123456789")
    lock.release(lock.DEFAULT_REPOSITORY, path)
    assert state["ref"] is None and not path.exists()


def test_busy_global_writer_must_not_be_stolen(monkeypatch, tmp_path):
    state = configure(monkeypatch)
    state["ref"] = "c" * 40
    with pytest.raises(RuntimeError, match="global writer busy"):
        lock.acquire(lock.DEFAULT_REPOSITORY, tmp_path / "lock.json", wait_seconds=0)
    assert state["ref"] == "c" * 40
    assert not (tmp_path / "lock.json").exists()


def test_remote_owner_sha_swap_fails_closed(monkeypatch, tmp_path):
    state = configure(monkeypatch)
    path = tmp_path / "lock.json"
    lock.acquire(lock.DEFAULT_REPOSITORY, path, wait_seconds=0)
    state["ref"] = "c" * 40
    with pytest.raises(RuntimeError, match="different writer"):
        lock.verify(lock.DEFAULT_REPOSITORY, path)
    with pytest.raises(RuntimeError, match="different writer"):
        lock.release(lock.DEFAULT_REPOSITORY, path)
    assert state["ref"] == "c" * 40


def test_release_if_held_noop(monkeypatch, tmp_path):
    configure(monkeypatch)
    lock.release(lock.DEFAULT_REPOSITORY, tmp_path / "missing.json", if_held=True)
    with pytest.raises(RuntimeError, match="not acquired"):
        lock.verify(lock.DEFAULT_REPOSITORY, tmp_path / "missing.json")
