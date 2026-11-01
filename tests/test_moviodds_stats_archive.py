"""Offline regressions for MoviOdds observation storage and Drive JSON export."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "api"), str(ROOT / "scripts")]

import pytest

from tbt.services.moviodds_stats import save_observations, save_final_scan_receipt, export_final
from moviodds_drive_archive import (
    _json_bytes, fetch_daily_final, upload_archive, _sha,
)

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)


class Exists(Exception):
    status_code = 409


class Table:
    def __init__(self):
        self.entities = {}

    def create_entity(self, row):
        key = row["PartitionKey"], row["RowKey"]
        if key in self.entities:
            raise Exists()
        self.entities[key] = dict(row)

    def get_entity(self, *, partition_key, row_key):
        return self.entities[(partition_key, row_key)]

    def query_entities(self, *, query_filter):
        partition = query_filter.split("'")[1]
        return [dict(v) for (p, _), v in self.entities.items() if p == partition]


def _mark_completed_day_scanned(table):
    save_final_scan_receipt(
        table, date_utc="2026-11-01", raw_count=1, accepted_count=1,
        collected_at=NOW + timedelta(days=1),
    )


def test_no_false_green_archive_without_post_day_scan():
    table = Table()
    save_observations(table, [observation()], completed=True, collected_at=NOW)
    with pytest.raises(Exception, match="no post-day verified scan"):
        export_final(days=["2026-11-01"], table=table)


def observation(finished=True, *, aces=3):
    return {
        "fixture_id" if finished else "id": "203862751",
        "home": "Akasha Urhobo", "away": "Julieta Pareja",
        "status": "finished" if finished else "ongoing",
        "in_play": not finished,
        "final_score": "4-6,1-6" if finished else None,
        "finished_at": "2026-11-01T08:30:00Z" if finished else None,
        "kickoff_utc": "2026-11-01T06:30:00Z",
        "stats": {
            "sport": "tennis", "updated_at": "2026-11-01T08:29:10Z",
            "surface": "Hard", "format": "best_of_3",
            "home": {"aces": aces, "double_faults": 4,
                     "first_serve_win_pct": 52,
                     "break_point_conversion_pct": 17},
            "away": {"aces": 1, "double_faults": 3,
                     "first_serve_win_pct": 79,
                     "break_point_conversion_pct": 42},
        },
    }


def test_verified_final_stats_and_repeat_idempotence():
    table = Table()
    row = observation()
    first = save_observations(table, [row], completed=True, collected_at=NOW)
    second = save_observations(table, [row], completed=True, collected_at=NOW)
    assert first["written"] == 1
    assert second["duplicate"] == 1 and second["written"] == 0
    _mark_completed_day_scanned(table)
    result = export_final(days=["2026-11-01"], table=table)
    assert result["verified"] and result["count"] == 1
    assert result["records"][0]["payload"]["stats"]["home"]["aces"] == 3
    assert "live" not in result["records"][0]["payload"]["status"]


def test_changed_final_observation_quarantined_not_overwritten():
    table = Table()
    save_observations(table, [observation()], completed=True, collected_at=NOW)
    result = save_observations(table, [observation(aces=4)],
                               completed=True, collected_at=NOW)
    assert result["conflict"] == 1 and result["written"] == 0
    _mark_completed_day_scanned(table)
    exported = export_final(days=["2026-11-01"], table=table)
    assert exported["records"][0]["payload"]["stats"]["home"]["aces"] == 3


def test_live_is_never_exported_as_final():
    table = Table()
    row = observation(False)
    first = save_observations(table, [row], completed=False, collected_at=NOW)
    assert first["written"] == 1
    _mark_completed_day_scanned(table)
    assert export_final(days=["2026-11-01"], table=table)["count"] == 0
    assert save_observations(table, [row], completed=False, collected_at=NOW)["duplicate"] == 1


@pytest.mark.parametrize("malformed", [
    {"fixture_id": "203862751", "status": "live"},
    {"fixture_id": "203862751", "status": "finished", "final_score": ""},
    {"fixture_id": "203862751", "status": "finished", "final_score": "6-0,6-0",
     "finished_at": "2026-11-01T08:30:00Z", "home": "P", "away": "Q",
     "stats": {"sport": "tennis", "updated_at": "2026-11-01T08:29:10Z",
               "home": {"aces": -1}, "away": {}}},
])
def test_incomplete_or_invalid_finished_stats_rejected(malformed):
    table = Table()
    result = save_observations(table, [malformed], completed=True, collected_at=NOW)
    assert result["written"] == 0 and result["rejected"] == 1


def test_tampered_azure_source_digest_refused():
    table = Table()
    save_observations(table, [observation()], completed=True, collected_at=NOW)
    entity = next(iter(table.entities.values()))
    entity["payload_json"] = entity["payload_json"].replace('"aces":3', '"aces":8')
    _mark_completed_day_scanned(table)
    with pytest.raises(Exception, match="digest mismatch"):
        export_final(days=["2026-11-01"], table=table)


class Response:
    def __init__(self, *, obj=None, raw=None):
        self.obj = obj
        self.raw = raw

    def raise_for_status(self):
        return None

    def json(self):
        return self.obj

    def iter_content(self, *, chunk_size):
        yield self.raw or b""


class ArchiveSession:
    def __init__(self, existing=None, content=None):
        self.existing = existing or []
        self.content = content
        self.posted = None

    def get(self, url, *, params=None, timeout=None, stream=None):
        if params and params.get("alt") == "media":
            return Response(raw=self.content)
        if url.endswith("moviodds-stats-worker"):
            return Response(raw=self.content)
        return Response(obj={"files": self.existing})

    def post(self, url, *, params, headers, data, timeout):
        self.posted = (url, params, headers, data)
        assert headers["Content-Type"].startswith("multipart/related")
        return Response(obj={
            "id": "new-file", "name": self.file_name,
            "parents": ["folder"], "mimeType": "application/json",
        })


def test_drive_archive_upload_and_full_remote_readback():
    export = {"schema": 1, "source": "moviodds", "verified": True,
              "days": ["2026-11-01"], "count": 0, "records": []}
    body = _json_bytes(export)
    fake = ArchiveSession(content=body)
    fake.file_name = f"moviodds-tennis-final-2026-11-01-{_sha(body)[:16]}.json"
    result = upload_archive(fake, date_utc="2026-11-01",
                            folder_id="folder", export=export)
    assert result["status"] == "verified_archived"
    assert body in fake.posted[-1]


def test_drive_archive_unchanged_duplicate_is_readback_verified():
    export = {"schema": 1, "source": "moviodds", "verified": True,
              "days": ["2026-11-01"], "count": 0, "records": []}
    body = _json_bytes(export)
    fake = ArchiveSession(existing=[{"id": "old-file"}], content=body)
    result = upload_archive(fake, date_utc="2026-11-01",
                            folder_id="folder", export=export)
    assert result["status"] == "already_archived"
    assert fake.posted is None


def test_drive_corrupted_prior_archive_fails_closed():
    export = {"schema": 1, "source": "moviodds", "verified": True,
              "days": ["2026-11-01"], "count": 0, "records": []}
    fake = ArchiveSession(existing=[{"id": "old-file"}], content=b"tampered")
    with pytest.raises(ValueError, match="readback mismatch"):
        upload_archive(fake, date_utc="2026-11-01",
                       folder_id="folder", export=export)
