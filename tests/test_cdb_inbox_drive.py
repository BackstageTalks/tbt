"""Realistic synthetic Drive tree intake, metadata checkpoint and fail-closed guards."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts.cdb_inbox_drive import BASE, fetch, _fingerprint

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
    fetched = [item for item in first["files"] if item["status"] == "fetched"]
    assert len(fetched) == 1
    assert fetched[0]["source_path"] == "/atp_matches_2026.csv"
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
    assert set(drive.file_reads[:3]) == {ID1, ID2, ID3}
    assert drive.file_reads[-1] == ID2


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


def test_match_source_prioritized_without_dropping_other_folders(tmp_path):
    """A small per-run budget must reach exact ATP/WTA match sources first."""
    odds_id = "ffffffffffffffff"
    match_id = "gggggggggggggggg"
    career_id = "hhhhhhhhhhhhhhhh"
    odds_folder = "iiiiiiiiiiiiiiii"
    match_folder = "jjjjjjjjjjjjjjjj"
    service_folder = "kkkkkkkkkkkkkkkk"

    class MixedSources(Drive):
        def __init__(self):
            super().__init__()
            self.blobs = {
                odds_id: b"odds", match_id: b"matches", career_id: b"career"
            }
            self.modified = {file_id: "2026-10-20T00:00:00Z"
                             for file_id in self.blobs}

        def get(self, url, params=None, timeout=None):
            if url != BASE:
                return super().get(url, params=params, timeout=timeout)
            parent = params["q"]
            if ROOT in parent:
                return Response(data={"files": [
                    {"id": odds_folder, "name": "02_KURZY_A_ODDS",
                     "mimeType": "application/vnd.google-apps.folder"},
                    {"id": service_folder, "name": "04_SERVIS_RETURN_STATISTIKY",
                     "mimeType": "application/vnd.google-apps.folder"},
                    {"id": match_folder, "name": "01_ZAPASY_A_VYSLEDKY",
                     "mimeType": "application/vnd.google-apps.folder"},
                ]})
            if odds_folder in parent:
                return Response(data={"files": [self.item(odds_id, "odds.csv")]})
            if service_folder in parent:
                return Response(data={"files": [
                    self.item(career_id, "atp_serve_1991_2026_52week_career.csv")]})
            if match_folder in parent:
                return Response(data={"files": [self.item(match_id, "atp_matches_2026.csv")]})
            raise AssertionError(parent)

    drive = MixedSources()
    previous = None
    for count, expected in enumerate((match_id, odds_id, career_id), 1):
        kwargs = {"state_path": previous} if previous else {}
        state = tmp_path / f"state-{count}.json"
        report = fetch(ROOT, tmp_path / f"raw-{count}", session=drive,
                       next_state_path=state, max_files=1, **kwargs)
        assert drive.file_reads[-1] == expected
        assert report["fetched"] == 1
        assert report["pending_supported"] == 3 - count
        previous = state
    assert drive.file_reads == [match_id, odds_id, career_id]



class FailedHTTPResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def raise_for_status(self):
        raise RuntimeError(f"HTTP {self.status_code}")


def test_transient_folder_http_500_retries_then_recovers_without_skipping(tmp_path, monkeypatch):
    delays = []
    monkeypatch.setattr("scripts.cdb_inbox_drive.time.sleep", delays.append)

    class OnceFailedDrive(Drive):
        calls = 0
        def get(self, url, params=None, timeout=None):
            if url == BASE and CHILD in params["q"]:
                self.calls += 1
                if self.calls == 1:
                    return FailedHTTPResponse(500)
            return super().get(url, params=params, timeout=timeout)

    drive = OnceFailedDrive()
    report = fetch(ROOT, tmp_path / "input", session=drive,
                   next_state_path=tmp_path / "next.json")
    assert report["fetched"] == 3
    assert drive.calls == 2
    assert delays == [1]
    assert (tmp_path / "next.json").exists()


def test_repeated_http_503_never_writes_checkpoint(tmp_path, monkeypatch):
    delays = []
    monkeypatch.setattr("scripts.cdb_inbox_drive.time.sleep", delays.append)

    class BrokenDrive(Drive):
        calls = 0
        def get(self, url, params=None, timeout=None):
            if url == BASE:
                self.calls += 1
                return FailedHTTPResponse(503)
            return super().get(url, params=params, timeout=timeout)

    drive = BrokenDrive()
    with pytest.raises(RuntimeError, match="HTTP 503"):
        fetch(ROOT, tmp_path / "raw", session=drive,
              next_state_path=tmp_path / "next.json")
    assert drive.calls == 4
    assert delays == [1, 2, 4]
    assert not (tmp_path / "next.json").exists()


def test_http_403_is_not_retried_or_checkpointed(tmp_path, monkeypatch):
    delays = []
    monkeypatch.setattr("scripts.cdb_inbox_drive.time.sleep", delays.append)

    class ForbiddenDrive(Drive):
        calls = 0
        def get(self, url, params=None, timeout=None):
            if url == BASE:
                self.calls += 1
                return FailedHTTPResponse(403)
            return super().get(url, params=params, timeout=timeout)

    drive = ForbiddenDrive()
    with pytest.raises(RuntimeError, match="HTTP 403"):
        fetch(ROOT, tmp_path / "raw", session=drive,
              next_state_path=tmp_path / "next.json")
    assert drive.calls == 1
    assert not delays
    assert not (tmp_path / "next.json").exists()


def test_transient_media_http_502_resumes_bounded_file_intake(tmp_path, monkeypatch):
    delays = []
    monkeypatch.setattr("scripts.cdb_inbox_drive.time.sleep", delays.append)

    class OnceFailedMedia(Drive):
        failed = False
        def get(self, url, params=None, timeout=None):
            if url.endswith("/" + ID1) and not self.failed:
                self.failed = True
                return FailedHTTPResponse(502)
            return super().get(url, params=params, timeout=timeout)

    drive = OnceFailedMedia()
    report = fetch(ROOT, tmp_path / "raw", session=drive,
                   next_state_path=tmp_path / "next.json")
    assert report["fetched"] == 3
    assert delays == [1]
    assert (tmp_path / "next.json").exists()


def test_targeted_replay_revisits_old_processed_source_without_cursor_reset(tmp_path):
    """Parser upgrades can re-run selected raw sources without re-downloading 2k files."""
    drive = Drive()
    first_state = tmp_path / "state-1.json"
    fetch(ROOT, tmp_path / "initial", session=drive, next_state_path=first_state)
    before = json.loads(first_state.read_text())
    assert len(drive.file_reads) == 3
    drive.file_reads.clear()

    second_state = tmp_path / "state-2.json"
    result = fetch(ROOT, tmp_path / "replay", session=drive,
                   state_path=first_state, next_state_path=second_state,
                   replay_ids={ID2})
    assert drive.file_reads == [ID2]
    assert result["explicit_replay_requested"] == 1
    assert result["explicit_replay_completed"] == 1
    assert result["replayed_from_checkpoint"] == 1
    assert result["fetched"] == 1
    assert result["pending_supported"] == 0
    assert json.loads(second_state.read_text()) == before
    assert json.loads((tmp_path / "drive_manifest.json").read_text())["production_mutated"] is False

    # Normal dispatches do not silently replay unchanged raw files.
    drive.file_reads.clear()
    third = fetch(ROOT, tmp_path / "third", session=drive,
                  state_path=second_state, next_state_path=tmp_path / "state-3.json")
    assert third["fetched"] == 0
    assert third["explicit_replay_requested"] == 0
    assert drive.file_reads == []


def test_replay_fail_closed_on_unknown_invalid_and_unbounded_selections(tmp_path):
    drive = Drive()
    for requested, message in (
        ({"unverified"}, "Invalid Drive replay file ID"),
        ({"zzzzzzzzzzzzzzzz"}, "not present"),
        ({ID1, ID2}, "exceeds bounded per-run allowance"),
    ):
        out = tmp_path / ("test-" + str(len(requested)) + message[:4])
        with pytest.raises(ValueError, match=message):
            fetch(ROOT, out, session=drive, max_files=1,
                  next_state_path=out / "state.json", replay_ids=requested)
        assert not (out / "state.json").exists()
    assert drive.file_reads == []


def test_replay_rejects_known_but_unsupported_file_without_checkpoint(tmp_path):
    drive = Drive()
    with pytest.raises(ValueError, match="unsupported or oversized"):
        fetch(ROOT, tmp_path / "blocked", session=drive,
              next_state_path=tmp_path / "blocked-state.json", replay_ids={ID4})
    assert not (tmp_path / "blocked-state.json").exists()
    assert drive.file_reads == []


def test_only_drive_folder_tour_upgrade_replays_existing_checkpoint_once(tmp_path):
    dedicated_atp = "mmmmmmmmmmmmmmmm"

    class DedicatedATPDrive(Drive):
        def get(self, url, params=None, timeout=None):
            if url != BASE:
                return super().get(url, params=params, timeout=timeout)
            parent = params["q"]
            if ROOT in parent:
                return Response(data={"files": [{
                    "id": dedicated_atp, "name": "ATP",
                    "mimeType": "application/vnd.google-apps.folder",
                }]})
            if dedicated_atp in parent:
                return Response(data={"files": [self.item(ID1, "X (99).csv")]})
            raise AssertionError(parent)

    drive = DedicatedATPDrive()
    original = drive.item(ID1, "X (99).csv")
    old_fields = ("id", "name", "mimeType", "size", "md5Checksum", "modifiedTime")
    old_fingerprint = hashlib.sha256(json.dumps(
        [str(original.get(field) or "") for field in old_fields],
        ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()
    assert _fingerprint(dict(original, path="/ATP/X (99).csv")) != old_fingerprint
    assert _fingerprint(dict(original, path="/X (99).csv")) == old_fingerprint
    # A source with a tour in its own filename must keep its old SHA key.
    assert _fingerprint(dict(original, name="atp_matches_2026.csv",
                            path="/ATP/atp_matches_2026.csv")) == hashlib.sha256(
        json.dumps([str(dict(original, name="atp_matches_2026.csv").get(field) or "")
                    for field in old_fields],
                   ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()

    old_checkpoint = tmp_path / "legacy.json"
    old_checkpoint.write_text(json.dumps({
        "schema": 1, "folder_id": ROOT,
        "processed": {ID1: old_fingerprint},
    }))
    upgraded_checkpoint = tmp_path / "upgraded.json"
    first = fetch(ROOT, tmp_path / "upgrade-input", session=drive,
                  state_path=old_checkpoint, next_state_path=upgraded_checkpoint)
    assert first["fetched"] == 1
    assert first["previously_seen"] == 0
    assert first["files"][0]["source_path"] == "/ATP/X (99).csv"
    second = fetch(ROOT, tmp_path / "next-input", session=drive,
                   state_path=upgraded_checkpoint, next_state_path=tmp_path / "next.json")
    assert second["fetched"] == 0
    assert second["previously_seen"] == 1
    assert drive.file_reads == [ID1]
