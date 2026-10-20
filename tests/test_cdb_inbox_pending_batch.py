"""No-network regression coverage for private staged CDB source and runner release."""
from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import tarfile

import pytest

from scripts import cdb_inbox_pending_batch as pending

ROOT_ID = "1jzdzztz8cXquO8VDswqE19PHupQau-xM"


def example_source(work: Path, *, base="a" * 40):
    source = work / "source"
    normalized = source / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)
    file = normalized / "atp_file.csv"
    file.write_text("league,tourney_date,winner_name,loser_name\natp,20261019,A,B\n")
    report = {
        "schema": 1, "state": "SOURCE_ONLY",
        "normalized": [{"path": "work/source/normalized/atp_file.csv", "tour": "atp"}],
        "counts": {"normalized_rows": 1},
    }
    (source / "report.json").write_text(json.dumps(report))
    state = work / "private-state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "original-sha").write_text(base)
    next_bytes = b'{"schema":1,"processed":{"file-a":"digest"}}\n'
    (state / "next.json").write_bytes(next_bytes)
    return next_bytes


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    work = tmp_path / "work"
    monkeypatch.setattr(pending, "ROOT", work)
    monkeypatch.setattr(pending, "ARTIFACT", work / "pending" / "batch.tar.gz")
    monkeypatch.setattr(pending, "MANIFEST", work / "pending" / "manifest.json")
    monkeypatch.setenv("GH_TOKEN", "fake-private-token")
    return work


def fake_private_release(work):
    release = {}
    def gh(args, missing_ok=False):
        if args[0] == "api":
            return json.dumps({"tag_name": pending.PENDING_TAG}) if release else None
        if args[:2] == ["release", "create"]:
            assert not release
            release["batch.tar.gz"] = pending.ARTIFACT.read_bytes()
            release["manifest.json"] = pending.MANIFEST.read_bytes()
            return ""
        if args[:2] == ["release", "download"]:
            folder = Path(args[args.index("-D")+1])
            folder.mkdir(parents=True, exist_ok=True)
            for name, data in release.items():
                (folder / name).write_bytes(data)
            return ""
        if args[:2] == ["release", "delete"]:
            release.clear()
            return ""
        raise AssertionError("Unexpected GitHub action: " + repr(args))
    return release, gh


def test_persist_then_restore_same_private_source_without_drive_refetch(isolated, monkeypatch):
    next_bytes = example_source(isolated)
    store, gh = fake_private_release(isolated)
    monkeypatch.setattr(pending, "_gh", gh)
    pending.persist(ROOT_ID)
    assert store["batch.tar.gz"]
    assert store["manifest.json"]
    shutil.rmtree(isolated / "source")
    (isolated / "private-state" / "next.json").unlink()
    assert pending.restore(ROOT_ID) is True
    assert (isolated / "source/normalized/atp_file.csv").is_file()
    assert (isolated / "private-state/next.json").read_bytes() == next_bytes
    # A repeated staging request must not overwrite or generate another release.
    pending.persist(ROOT_ID)
    pending._clear()
    assert not store


def test_already_consumed_batch_cleans_up_before_fetching_next(isolated, monkeypatch):
    next_bytes = example_source(isolated)
    store, gh = fake_private_release(isolated)
    monkeypatch.setattr(pending, "_gh", gh)
    pending.persist(ROOT_ID)
    shutil.rmtree(isolated / "source")
    (isolated / "private-state" / "next.json").unlink()
    (isolated / "private-state" / "current.json").write_bytes(next_bytes)
    (isolated / "private-state" / "original-sha").write_text("b" * 40)
    assert pending.restore(ROOT_ID) is False
    assert not store


def test_checkpoint_mismatch_does_not_restore_or_discard_staged_data(isolated, monkeypatch):
    example_source(isolated)
    store, gh = fake_private_release(isolated)
    monkeypatch.setattr(pending, "_gh", gh)
    pending.persist(ROOT_ID)
    shutil.rmtree(isolated / "source")
    (isolated / "private-state" / "original-sha").write_text("b" * 40)
    (isolated / "private-state" / "current.json").write_bytes(b"unrelated")
    with pytest.raises(pending.PendingInvalid, match="checkpoint moved"):
        pending.restore(ROOT_ID)
    assert store
    assert not (isolated / "source").exists()


def test_tampered_archive_is_detected_and_never_restored(isolated, monkeypatch):
    example_source(isolated)
    store, gh = fake_private_release(isolated)
    monkeypatch.setattr(pending, "_gh", gh)
    pending.persist(ROOT_ID)
    store["batch.tar.gz"] = b"tampered"
    shutil.rmtree(isolated / "source")
    with pytest.raises(pending.PendingInvalid, match="digest"):
        pending.restore(ROOT_ID)
    assert not (isolated / "source").exists()


def test_bad_member_path_rejected_before_extraction():
    payload = b"data"
    tarblob = io.BytesIO()
    with tarfile.open(fileobj=tarblob, mode="w:gz") as tar:
        info = tarfile.TarInfo("../bad.csv")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    doc = {"schema":1,"files":{"source/report.json": "a"*64,
                                "private-state/next.json": "b"*64,
                                "../bad.csv": pending.sha256(payload)}}
    with pytest.raises(pending.PendingInvalid, match="Unsafe"):
        pending._unpack(doc,tarblob.getvalue())


def test_only_successful_checkpoint_clears_pending_batch():
    workflow = Path(".github/workflows/cdb-drive-inbox.yml").read_text()
    assert "await-cdb-writer-idle:" not in workflow
    assert "Observe CDB writer only AFTER normalized data preparation" in workflow
    assert workflow.index("Read all BlinQ_data descendants") < workflow.index("Observe CDB writer")
    assert workflow.index("Persist prepared batch privately") < workflow.index("Download entire manifest")
    assert "steps.prepared.outputs.restored != 'true'" in workflow
    assert "steps.writer_gate.outputs.ready == 'true'" in workflow
    assert "steps.writer_gate.outputs.ready == 'false'" in workflow
    assert "python scripts/cdb_inbox_pending_batch.py persist" in workflow
    assert "python scripts/cdb_inbox_pending_batch.py clear" in workflow
    assert workflow.index("CDB_INBOX_PROGRESS_PRIVATE_READBACK_VERIFIED") < workflow.index("Clear PRIVATE prepared batch")
    assert "--wait-seconds 0" in workflow
    assert "store.upload_bundle(" in workflow
    assert "CDB_PRODUCTION_READBACK_VERIFIED" in workflow
