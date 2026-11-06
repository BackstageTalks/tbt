"""Concurrent Azure/Firestore Results archive writers must never lose rows."""
from __future__ import annotations

from copy import deepcopy

import pytest

from tbt.services import results_archive
from tbt.services.admin_storage import AdminStorageUnavailable
from test_results_archive_runtime import Table, VersionConflict, _feed, _status


def same_shard_rows(wanted=3):
    by_slot = {}
    for index in range(1, 80):
        event = str(880000 + index)
        rows = results_archive.settled_archive_candidates(_feed(event), _status(event))
        assert len(rows) == 1
        row = rows[0]
        slot, _ = results_archive._slot(row)
        by_slot.setdefault(slot, []).append(row)
        if len(by_slot[slot]) >= wanted:
            return by_slot[slot][:wanted]
    raise AssertionError("Could not build independent matching Azure result shards")


def keys(table):
    archive = []
    for item in table.items.values():
        payload = results_archive._decode_runtime_ui_payload(item["payload"])
        archive.extend(payload["rows"].values())
    return {row["event_id"] for row in archive}


class ConcurrentUpdateTable(Table):
    pending = None
    conflicts = 0

    def update_entity(self, entity, *, mode, etag, match_condition):
        if self.pending is not None:
            # An independent worker wins a write *after* our read, before
            # our conditional update. A blind upsert would erase its row.
            row = self.pending
            self.pending = None
            key = entity["PartitionKey"], entity["RowKey"]
            slot, identity = results_archive._slot(row)
            assert slot == key[1]
            stored = self.items[key]
            payload = results_archive._decode_runtime_ui_payload(stored["payload"])
            payload["rows"][identity] = deepcopy(row)
            stored["payload"] = results_archive._encode_runtime_ui_payload(payload)
            self.versions[key] += 1
            self.conflicts += 1
            raise VersionConflict()
        return super().update_entity(
            entity, mode=mode, etag=etag, match_condition=match_condition
        )


class ConcurrentCreateTable(Table):
    pending = None
    conflicts = 0

    def create_entity(self, entity):
        if self.pending is not None:
            row = self.pending
            self.pending = None
            slot, identity = results_archive._slot(row)
            assert slot == entity["RowKey"]
            created = dict(entity)
            created["payload"] = results_archive._encode_runtime_ui_payload({
                "schema": 1, "rows": {identity: row}
            })
            super().create_entity(created)
            self.conflicts += 1
            raise VersionConflict()
        return super().create_entity(entity)


def test_interleaved_conditional_update_preserves_both_workers(monkeypatch):
    previous, concurrent, incoming = same_shard_rows(3)
    table = ConcurrentUpdateTable()
    monkeypatch.setattr(results_archive, "_table", lambda _: table)
    assert results_archive.save_settled_results_archive([previous])["added"] == 1
    table.pending = concurrent
    saved = results_archive.save_settled_results_archive([incoming])
    assert saved == {"eligible": 1, "added": 1, "updated": 0, "verified": True}
    assert table.conflicts == 1
    assert keys(table) == {previous["event_id"], concurrent["event_id"], incoming["event_id"]}
    assert {x["event_id"] for x in results_archive.load_settled_results_archive()} == keys(table)
    assert results_archive.save_settled_results_archive([incoming])["added"] == 0


def test_interleaved_create_retries_after_other_worker_created_shard(monkeypatch):
    first, concurrent = same_shard_rows(2)
    table = ConcurrentCreateTable()
    table.pending = concurrent
    monkeypatch.setattr(results_archive, "_table", lambda _: table)
    saved = results_archive.save_settled_results_archive([first])
    assert saved["added"] == 1 and saved["verified"] is True
    assert table.conflicts == 1
    assert keys(table) == {first["event_id"], concurrent["event_id"]}


def test_exhausted_cas_conflicts_fail_closed_without_erasing_prior_row(monkeypatch):
    previous, incoming = same_shard_rows(2)

    class AlwaysContended(Table):
        attempts = 0

        def update_entity(self, entity, *, mode, etag, match_condition):
            self.attempts += 1
            raise VersionConflict()

    table = AlwaysContended()
    monkeypatch.setattr(results_archive, "_table", lambda _: table)
    results_archive.save_settled_results_archive([previous])
    with pytest.raises(AdminStorageUnavailable, match="CAS retry exhausted"):
        results_archive.save_settled_results_archive([incoming])
    assert table.attempts == 8
    assert keys(table) == {previous["event_id"]}


def test_missing_etag_fails_closed_instead_of_blind_upsert(monkeypatch):
    previous, incoming = same_shard_rows(2)

    class MissingEtagTable(Table):
        missing = False

        def get_entity(self, *, partition_key, row_key):
            result = super().get_entity(partition_key=partition_key, row_key=row_key)
            return dict(result) if self.missing else result

    table = MissingEtagTable()
    monkeypatch.setattr(results_archive, "_table", lambda _: table)
    results_archive.save_settled_results_archive([previous])
    table.missing = True
    with pytest.raises(AdminStorageUnavailable, match="ETag unavailable"):
        results_archive.save_settled_results_archive([incoming])
    assert keys(table) == {previous["event_id"]}
