"""Canonical release publication must require the private cross-repo owner lock."""
import pytest
import sys

from scripts import cdb_global_writer_lock, release_store


def test_canonical_upload_gate_happens_before_any_remote_release_action(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setitem(sys.modules, "cdb_global_writer_lock", cdb_global_writer_lock)
    obj = object.__new__(release_store.ReleaseStore)
    obj.repository = "BackstageTalks/tbt-data"
    obj.tag = "tbt-data-v1"
    obj.directory = tmp_path
    operations = []
    monkeypatch.setattr(cdb_global_writer_lock, "verify",
                        lambda repo, path: operations.append(("verify", repo, path)) or {})
    monkeypatch.setattr(release_store.ReleaseStore, "_remote_bundle_files",
                        lambda self: operations.append(("remote",)) or {})
    with pytest.raises(FileNotFoundError, match="Bundle asset is missing"):
        obj.upload_bundle([tmp_path / "missing.parquet"])
    assert operations[0][0] == "verify"
    assert operations[0][1] == "BackstageTalks/tbt-data"
    assert operations[1] == ("remote",)


def test_training_release_obeys_same_lock(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setitem(sys.modules, "cdb_global_writer_lock", cdb_global_writer_lock)
    obj = object.__new__(release_store.ReleaseStore)
    obj.repository = "BackstageTalks/tbt-data"
    obj.tag = "tbt-training-table-v1"
    obj.directory = tmp_path
    def refuse(repo, path):
        raise RuntimeError("No global writer lock")
    monkeypatch.setattr(cdb_global_writer_lock, "verify", refuse)
    with pytest.raises(RuntimeError, match="No global writer lock"):
        obj.upload_bundle([tmp_path / "dataset.parquet"])
