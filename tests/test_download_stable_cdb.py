"""Coherent CDB readback must never accept a manifest/partition race."""
import hashlib
import json

import pytest

from scripts import download_stable_cdb as subject


def digest(data):
    return hashlib.sha256(data).hexdigest()


def test_retries_only_when_remote_manifest_moves(monkeypatch, tmp_path):
    prior = b'{"files":{}}'
    current = b'{"files":{"history-2022.parquet":{"sha256":"' + digest(b"latest").encode() + b'"}}}'
    calls = []

    class Store:
        def __init__(self, repository, tag, directory):
            self.directory = directory
            self.directory.mkdir(parents=True, exist_ok=True)

        def _asset_names(self):
            return {subject.MANIFEST}

        def _download_asset(self, name):
            # first attempt: old pre-manifest, latest post-manifest;
            # second attempt: stable latest manifest.
            calls.append("manifest")
            value = prior if len(calls) == 1 else current
            (self.directory / subject.MANIFEST).write_bytes(value)

        def download(self, **kwargs):
            calls.append("bundle")
            assert kwargs["require_bundle_manifest"]
            if len([c for c in calls if c == "bundle"]) == 1:
                raise RuntimeError("Release bundle checksum mismatch for history-2022.parquet")
            (self.directory / "history-2022.parquet").write_bytes(b"latest")

    monkeypatch.setattr(subject, "ReleaseStore", Store)
    report = subject.download_stable("repo", "tag", tmp_path / "history")
    assert report["status"] == "verified"
    assert report["attempt"] == 2
    assert report["manifest_sha256"] == digest(current)


def test_stable_manifest_corruption_fails_closed(monkeypatch, tmp_path):
    manifest = b'{"files":{}}'

    class Store:
        def __init__(self, repository, tag, directory):
            self.directory = directory
            self.directory.mkdir(parents=True, exist_ok=True)

        def _asset_names(self):
            return {subject.MANIFEST}

        def _download_asset(self, name):
            (self.directory / subject.MANIFEST).write_bytes(manifest)

        def download(self, **kwargs):
            raise RuntimeError("Release bundle checksum mismatch for history-2022.parquet")

    monkeypatch.setattr(subject, "ReleaseStore", Store)
    with pytest.raises(RuntimeError, match="manifest_moved=False"):
        subject.download_stable("repo", "tag", tmp_path / "history")
    assert not (tmp_path / "history").exists()
