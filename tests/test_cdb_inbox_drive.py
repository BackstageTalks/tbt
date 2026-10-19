"""Realistic synthetic Drive tree intake, metadata checkpoint and fail-closed guards."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts.cdb_inbox_drive import BASE, fetch

ROOT = "1jzdzztz8cXquO8VDswqE19PHupQau-xM"
CHILD = "aaaaaaaaaaaaaaaa"
ID1 = "bbbbbbbbbbbbbbbb"
ID2 = "cccccccccccccccc"
ID3 = "dddddddddddddddd"
ID4 = "eeeeeeeeeeeeeeee"


class Response:
    def __init__(self, *, data=None, content=b""):
        self.data, self.content = data, content

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class Drive:
    def __init__(self):
        self.blobs = {ID1: b"one", ID2: b"two", ID3: b"three"}
        self.modified = {ID1: "2026-10-19T09:00:00Z",
                         ID2: "2026-10-19T09:00:00Z",
                         ID3: "2026-10-19T09:00:00Z"}
        self.file_reads = []

    def item(self, file_id, name):
        raw = self.blobs[file_id]
        return {"id": file_id, "name": name, "mimeType": "text/csv",
                "size": str(len(raw)),
                "modifiedTime": self.modified[file_id],
                "md5Checksum": hashlib.md5(raw).hexdigest()}

    def get(self, url, params=None, timeout=None):
        if url != BASE:
            file_id = url.split("/")[-1]
            self.file_reads.append(file_id)
            return Response(content=self.blobs[file_id])
        selector = params["q"]
        if ROOT in selector:
            if not params.get("pageToken"):
                return Response(data={"files": [
                    {"id": CHILD, "name": "nested", "mimeType": "application/vnd.google-apps.folder"},
                    self.item(ID1, "atp_matches_2026.csv"),
                ], "nextPageToken": "next"})
            assert params["pageToken"] == "next"
            return Response(data={"files": [
                {"id": ID4, "name": "README.md", "mimeType": "text/markdown", "size": "20"},
            ]})
        if CHILD in selector:
            return Response(data={"files": [
                self.item(ID2, "wta_matches_2026.csv"),
                self.item(ID3, "second_atp.csv"),
            ]})
        raise AssertionError("Unexpected Drive parent: " + selector)


def test_recursive_bounded_batches_and_recoverable_checkpoint(tmp_path):
    drive = Drive()
    first = fetch(ROOT, tmp_path / "raw-1", session=drive, max_files=1,
                  next_state_path=tmp_path / "state-1.json")
    assert first["folders_seen"] == 2
    assert first["inventory_files"] == 4
    assert first["reviewed"] == 1
    assert first["fetched"] == 1
    assert first["pending_supported"] == 2
    assert len(drive.file_reads) == 1

    second = fetch(ROOT, tmp_path / "raw-2", session=drive,
                   state_path=tmp_path / "state-1.json", max_files=1,
                   next_state_path=tmp_path / "state-2.json")
    assert second["fetched"] == 1
    assert second["pending_supported"] == 1
    third = fetch(ROOT, tmp_path / "raw-3", session=drive,
                  state_path=tmp_path / "state-2.json", max_files=1,
                  next_state_path=tmp_path / "state-3.json")
    assert third["fetched"] == 1
    assert third["pending_supported"] == 0
    fourth = fetch(ROOT, tmp_path / "raw-4", session=drive,
                   state_path=tmp_path / "state-3.json", max_files=1,
                   next_state_path=tmp_path / "state-4.json")
    assert fourth["fetched"] == 0
    assert fourth["previously_seen"] == 4
    assert len(drive.file_reads) == 3
    assert json.loads((tmp_path / "state-4.json").read_text())["folder_id"] == ROOT


def test_changed_file_is_processed_again_but_unchanged_files_not_downloaded(tmp_path):
    drive = Drive()
    fetch(ROOT, tmp_path / "input", session=drive,
          next_state_path=tmp_path / "progress.json")
    assert len(drive.file_reads) == 3
    drive.blobs[ID2] = b"changed"
    drive.modified[ID2] = "2026-10-19T10:00:00Z"
    result = fetch(ROOT, tmp_path / "next", session=drive,
                   state_path=tmp_path / "progress.json",
                   next_state_path=tmp_path / "progress-next.json")
    assert result["fetched"] == 1
    assert result["pending_supported"] == 0
    assert drive.file_reads == [ID1, ID2, ID3, ID2]


def test_wrong_root_checkpoint_fails_closed(tmp_path):
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"schema": 1, "folder_id": "wrong",
                                  "processed": {}}))
    with pytest.raises(ValueError, match="wrong folder"):
        fetch(ROOT, tmp_path / "raw", session=Drive(), state_path=wrong)


def test_repeated_cursor_refuses_partial_inventory(tmp_path):
    class BadDrive(Drive):
        def get(self, url, params=None, timeout=None):
            if url == BASE:
                return Response(data={"files": [], "nextPageToken": "same"})
            return super().get(url, params=params, timeout=timeout)
    with pytest.raises(ValueError, match="repeated Drive page cursor"):
        fetch(ROOT, tmp_path / "raw", session=BadDrive())
