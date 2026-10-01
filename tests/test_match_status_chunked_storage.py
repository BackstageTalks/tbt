import hashlib
import json

from tbt.services import admin_storage


class ChunkTable:
    def __init__(self):
        self.rows = {}

    def upsert_entity(self, entity, mode=None):
        row = dict(entity)
        self.rows[(row["PartitionKey"], row["RowKey"])] = row

    def get_entity(self, partition_key, row_key):
        key = (partition_key, row_key)
        if key not in self.rows:
            raise KeyError(row_key)
        return dict(self.rows[key])

    def query_entities(self, query_filter=None):
        rows = list(self.rows.values())
        if not query_filter:
            return rows
        marker = "PartitionKey eq '"
        if marker in str(query_filter):
            key = str(query_filter).split(marker, 1)[1].split("'", 1)[0]
            return [row for row in rows if row.get("PartitionKey") == key]
        return rows

    def delete_entity(self, *, partition_key, row_key):
        self.rows.pop((partition_key, row_key), None)


def _large_pending(count=5000):
    pending = {}
    for i in range(count):
        digest = hashlib.sha256(f"match-{i}".encode()).hexdigest()
        pending[str(i)] = {
            "t": f"2026-09-{(i % 28) + 1:02d}T21:{i % 60:02d}:00+00:00",
            "s": digest[:24],
            "a": digest[8:32],
            "b": digest[16:40],
            "c": f"2026-10-01T{i % 24:02d}:{i % 60:02d}:00+00:00",
        }
    return pending


def test_oversized_match_status_snapshot_roundtrips_without_truncation(monkeypatch):
    table = ChunkTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)

    pending = _large_pending()
    saved = admin_storage.save_match_status_snapshot({
        "statuses": {
            "resolved": {
                "status": "win",
                "checked_at": "2026-10-01T02:00:00+00:00",
                "winner_id": "winner-1",
                "provider_status": "finished",
            }
        },
        "pending": pending,
        "tracked": len(pending) + 1,
        "due": len(pending),
        "budget_paused": True,
    })

    assert saved["pending_count"] == len(pending)
    manifest_row = table.get_entity("runtime", "match-status-worker")
    manifest = json.loads(manifest_row["payload"])
    assert manifest["__match_status_chunks__"] == 1
    assert manifest["chunks"] > 1

    chunks = [
        row for row in table.rows.values()
        if str(row.get("RowKey") or "").startswith("match-status-worker-chunk-")
    ]
    assert len(chunks) == manifest["chunks"]
    assert all(len(str(row["payload"]).encode("utf-16-le")) < 60_000 for row in chunks)

    restored = admin_storage.load_match_status_snapshot()
    assert restored["budget_paused"] is True
    assert restored["statuses"]["resolved"]["status"] == "win"
    assert restored["pending_count"] == len(pending)
    assert restored["pending"]["4999"]["s"] == pending["4999"]["s"]


def test_small_match_status_snapshot_replaces_chunks_and_cleans_old_rows(monkeypatch):
    table = ChunkTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)

    admin_storage.save_match_status_snapshot({"pending": _large_pending()})
    assert any(
        str(row.get("RowKey") or "").startswith("match-status-worker-chunk-")
        for row in table.rows.values()
    )

    admin_storage.save_match_status_snapshot({
        "pending": {
            "101": {
                "t": "2026-10-01T03:00:00+00:00",
                "s": "11", "a": "11", "b": "22", "c": "",
            }
        }
    })
    restored = admin_storage.load_match_status_snapshot()
    assert restored["pending_count"] == 1
    assert restored["pending"]["101"]["b"] == "22"
    assert not any(
        str(row.get("RowKey") or "").startswith("match-status-worker-chunk-")
        for row in table.rows.values()
    )


def test_match_status_snapshot_keeps_backlog_priority_diagnostics(monkeypatch):
    table = ChunkTable()
    monkeypatch.setattr(admin_storage, "_table", lambda name: table)

    saved = admin_storage.save_match_status_snapshot({
        "pending": {
            "101": {
                "t": "2026-10-01T08:00:00+00:00",
                "s": "11", "a": "11", "b": "22", "c": "",
            }
        },
        "priority_mode": True,
        "betting_day_start": "2026-10-01T04:00:00+00:00",
        "current_betting_day_due": 17,
        "backlog_due": 946,
        "runtime_limited": True,
    })

    assert saved["priority_mode"] is True
    assert saved["betting_day_start"] == "2026-10-01T04:00:00+00:00"
    assert saved["current_betting_day_due"] == 17
    assert saved["backlog_due"] == 946
    assert saved["runtime_limited"] is True

    restored = admin_storage.load_match_status_snapshot()
    assert restored["priority_mode"] is True
    assert restored["current_betting_day_due"] == 17
    assert restored["backlog_due"] == 946
