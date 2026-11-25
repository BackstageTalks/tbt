"""Orphaned-lock release: own run only, and only with a consistent CDB bundle."""
import pytest
import cdb_global_writer_lock as L

OWNER = "BackstageTalks/tbt/actions/runs/7/attempts/1"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("GITHUB_REPOSITORY", "BackstageTalks/tbt")
    monkeypatch.setenv("GITHUB_RUN_ID", "7")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")


def _setup(monkeypatch, owner, consistent=(True, "2 files consistent")):
    calls = []

    def api(repo, endpoint, method="GET", data=None):
        calls.append((method, endpoint))
        if endpoint.startswith("git/tags/"):
            return {"message": "owner=" + owner}
        return {}
    monkeypatch.setattr(L, "_api", api)
    monkeypatch.setattr(L, "_remote_lock", lambda r: {"object": {"sha": "abc"}})
    monkeypatch.setattr(L, "_bundle_consistent", lambda r: consistent)
    return calls


def test_releases_own_lock_when_bundle_consistent(monkeypatch):
    calls = _setup(monkeypatch, OWNER)
    assert L.release_orphan(L.DEFAULT_REPOSITORY).startswith("released")
    assert ("DELETE", "git/refs/tags/blinq-cdb-global-writer") in calls


def test_never_touches_other_runs_lock(monkeypatch):
    calls = _setup(monkeypatch, "BackstageTalks/tbt/actions/runs/8/attempts/1")
    assert "untouched" in L.release_orphan(L.DEFAULT_REPOSITORY)
    assert not any(m == "DELETE" for m, _ in calls)


def test_keeps_lock_when_bundle_inconsistent(monkeypatch):
    calls = _setup(monkeypatch, OWNER, (False, "digest mismatch history-2026.parquet"))
    with pytest.raises(RuntimeError):
        L.release_orphan(L.DEFAULT_REPOSITORY)
    assert not any(m == "DELETE" for m, _ in calls)


def test_no_lock_is_noop(monkeypatch):
    monkeypatch.setattr(L, "_remote_lock", lambda r: None)
    assert L.release_orphan(L.DEFAULT_REPOSITORY) == "no lock"
