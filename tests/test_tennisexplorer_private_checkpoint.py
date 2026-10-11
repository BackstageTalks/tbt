"""Offline fixtures for private TennisExplorer archive completeness / identity gates."""
from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_tennisexplorer_private_checkpoint import audit


YEAR = 2024
CATEGORY = "wta-single"
R = f"data/tennisexplorer/results/{CATEGORY}/{YEAR}"
D = f"data/tennisexplorer/enrichment/{CATEGORY}/{YEAR}"


def fixture(tmp: Path, *, complete=True, bad_year=False, bad_source=False, dup_member=False):
    days = []
    day = date(YEAR, 1, 1)
    while day.year == YEAR:
        days.append(day.isoformat())
        day += timedelta(days=1)
    if not complete:
        days = days[:3]
    csvrows = ("date,match_id,category,side1_display,side2_display\n"
               f"{'2023-06-01' if bad_year else '2024-01-01'},111,{CATEGORY},Player A,Player B\n")
    p = "date,category,status\n" + "".join(f"{day},{CATEGORY},ok\n" for day in days)
    resultmeta = dict(category=CATEGORY, year=YEAR, expected_days=366,
                      completed_days=len(days), missing_days_count=366-len(days),
                      complete=complete)
    detailmeta = dict(category=CATEGORY, year=YEAR, complete=complete)
    detail = dict(source="OtherSource" if bad_source else "TennisExplorer", match_id="111")
    members = {
        R + ".csv": csvrows,
        R + ".pages.csv": p,
        R + ".run_metadata.json": json.dumps(resultmeta),
        D + ".jsonl": json.dumps(detail) + "\n",
        D + ".run_metadata.json": json.dumps(detailmeta),
    }
    path = tmp / "data.tar.gz"
    with tarfile.open(path, "w:gz") as t:
        for name, text in members.items():
            raw = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            t.addfile(info, io.BytesIO(raw))
        if dup_member:
            first = next(iter(members))
            raw = members[first].encode()
            info = tarfile.TarInfo(first)
            info.size = len(raw)
            t.addfile(info, io.BytesIO(raw))
    return path, sha256(path.read_bytes()).hexdigest()


def test_complete_source_is_not_cdb_approved():
    with tempfile.TemporaryDirectory() as folder:
        archive, digest = fixture(Path(folder))
        report = audit(archive, CATEGORY, YEAR, digest)
        assert report["status"] == "SOURCE_STRUCTURALLY_COMPLETE_CDB_LINK_PENDING"
        assert report["counts"]["unique_successful_days"] == 366
        assert report["canonical_cell_delta_approved"] == 0
        assert report["production_cdb_modified"] is False
        assert report["source_use_rights_verified"] is False


def test_partial_coverage_is_quarantined():
    with tempfile.TemporaryDirectory() as folder:
        archive, digest = fixture(Path(folder), complete=False)
        report = audit(archive, CATEGORY, YEAR, digest)
        assert report["status"] == "PARTIAL_OR_CONFLICTED_QUARANTINE_NO_CDB"
        assert report["counts"]["missing_successful_days"] == 363


def test_other_year_rejected():
    with tempfile.TemporaryDirectory() as folder:
        archive, digest = fixture(Path(folder), bad_year=True)
        report = audit(archive, CATEGORY, YEAR, digest)
        assert "invalid_match_year" in report["issues"]


def test_invalid_detail_source_rejected():
    with tempfile.TemporaryDirectory() as folder:
        archive, digest = fixture(Path(folder), bad_source=True)
        report = audit(archive, CATEGORY, YEAR, digest)
        assert "invalid_details" in report["issues"]


def test_wrong_digest_rejected():
    with tempfile.TemporaryDirectory() as folder:
        archive, _ = fixture(Path(folder))
        try:
            audit(archive, CATEGORY, YEAR, "0" * 64)
            assert False, "digest mismatch was accepted"
        except ValueError as exc:
            assert "SOURCE_SHA256_MISMATCH" in str(exc)


def test_duplicate_tar_member_rejected():
    with tempfile.TemporaryDirectory() as folder:
        archive, digest = fixture(Path(folder), dup_member=True)
        try:
            audit(archive, CATEGORY, YEAR, digest)
            assert False, "duplicate member was accepted"
        except ValueError as exc:
            assert "Duplicate archive member" in str(exc)
