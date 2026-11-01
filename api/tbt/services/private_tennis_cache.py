"""Private Azure Table raw provider response cache (NOT canonical CDB).

The authenticated API route alone can access the backing table. CAS leases
serialize concurrent GitHub runners. Each accepted raw JSON response is also
appended to an immutable source-history record before publishing the latest
cache entry. Errors fail closed; no fallback to unmetered API requests.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid
import zlib

TABLE = "BlinQTennisRawCache"
PARTITION = "tennisapi1"
LEASE_SECONDS = 900
MAX_RAW_BYTES = 256_000
MAX_COMPRESSED_BYTES = 28_000  # Azure Table string properties are UTF-16 (64 KiB cap)


class CacheStoreUnavailable(RuntimeError):
    pass


def _key(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Invalid private provider cache key")
    return value


def _table(table=None):
    if table is not None:
        return table
    try:
        from .admin_storage import _azure_table
        return _azure_table(TABLE)
    except Exception as exc:
        raise CacheStoreUnavailable("Private cache storage unavailable") from exc


def _fetch(table, key):
    try:
        return table.get_entity(partition_key=PARTITION, row_key=key)
    except Exception as exc:
        from .admin_storage import _storage_not_found
        if _storage_not_found(exc):
            return None
        raise CacheStoreUnavailable("Private cache read unavailable") from exc


def _conflict(exc):
    code = getattr(exc, "status_code", None)
    return code in (409, 412) or any(k in type(exc).__name__.lower()
                                     for k in ("conflict", "precondition", "resourceexists"))


def _write(table, key, row, updated):
    if row is None:
        table.create_entity(updated)
        return
    from azure.core import MatchConditions
    etag = getattr(row, "metadata", {}).get("etag")
    if not etag:
        raise CacheStoreUnavailable("Private cache CAS ETag missing")
    table.update_entity(updated, mode="merge", etag=etag,
                        match_condition=MatchConditions.IfNotModified)


def _unpack(row):
    try:
        packed = str(row["body"])
        if len(packed) > 65_000:
            raise ValueError("Stored body too large")
        zipped = base64.b64decode(packed, validate=True)
        inflater = zlib.decompressobj()
        raw = inflater.decompress(zipped, MAX_RAW_BYTES + 1)
        if (not inflater.eof or inflater.unconsumed_tail or len(raw) > MAX_RAW_BYTES
                or hashlib.sha256(raw).hexdigest() != row["digest"]):
            raise ValueError("Invalid stored raw digest")
        value = json.loads(raw)
        if not isinstance(value, (dict, list)):
            raise ValueError("Invalid stored raw type")
        return value
    except (KeyError, ValueError, TypeError, zlib.error) as exc:
        raise CacheStoreUnavailable("Private cache integrity failure") from exc


def read(key, *, max_age, table=None, now=None):
    key = _key(key)
    if not isinstance(max_age, (int, float)) or not 0 <= max_age <= 30 * 86400:
        raise ValueError("Invalid raw response max-age")
    table = _table(table)
    when = time.time() if now is None else float(now)
    row = _fetch(table, key)
    if row is None:
        return {"status": "miss"}
    if row.get("state") == "pending":
        if float(row.get("lease_until", 0)) > when:
            return {"status": "busy"}
        return {"status": "miss"}
    if row.get("state") == "absent":
        return {"status": "miss"}
    if row.get("state") != "ready":
        raise CacheStoreUnavailable("Unknown private cache state")
    fetched = row.get("fetched_at")
    if type(fetched) not in (int, float) or fetched > when or when-fetched >= max_age:
        return {"status": "miss"}
    return {"status": "hit", "payload": _unpack(row),
            "fetched_at": fetched, "parser_version": str(row.get("parser_version") or "")}


def claim(key, owner, *, max_age, table=None, now=None):
    key = _key(key)
    if not isinstance(owner, str) or re.fullmatch(r"[0-9a-f]{32}", owner) is None:
        raise ValueError("Invalid lease owner")
    table = _table(table)
    when = time.time() if now is None else float(now)
    for attempt in range(12):
        existing = read(key, max_age=max_age, table=table, now=when)
        if existing["status"] in ("hit", "busy"):
            return existing
        row = _fetch(table, key)
        if row is not None and row.get("state") == "pending" and float(row.get("lease_until", 0)) > when:
            return {"status": "busy"}
        entity = {"PartitionKey": PARTITION, "RowKey": key, "state": "pending",
                  "owner": owner, "lease_until": when + LEASE_SECONDS}
        try:
            _write(table, key, row, entity)
            return {"status": "claimed"}
        except CacheStoreUnavailable:
            raise
        except Exception as exc:
            if not _conflict(exc):
                raise CacheStoreUnavailable("Private cache claim failed") from exc
            if attempt == 11:
                raise CacheStoreUnavailable("Private cache claim contention") from exc
            time.sleep(0.02)
    raise CacheStoreUnavailable("Private cache claim contention")


def abort(key, owner, *, table=None):
    key = _key(key)
    table = _table(table)
    row = _fetch(table, key)
    if row is None or row.get("state") != "pending" or row.get("owner") != owner:
        raise CacheStoreUnavailable("Private cache abort lease mismatch")
    entity = {"PartitionKey": PARTITION, "RowKey": key, "state": "absent",
              "owner": "", "lease_until": 0}
    try:
        _write(table, key, row, entity)
    except Exception as exc:
        raise CacheStoreUnavailable("Private cache abort CAS failed") from exc
    return {"status": "aborted"}


def publish(key, owner, payload, parser_version, *, table=None, now=None):
    key = _key(key)
    if not isinstance(owner, str) or not re.fullmatch(r"[0-9a-f]{32}", owner):
        raise ValueError("Invalid lease owner")
    if not isinstance(payload, (dict, list)):
        raise ValueError("Raw response must be JSON object or list")
    when = time.time() if now is None else float(now)
    try:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Non-JSON provider response") from exc
    packed = base64.b64encode(zlib.compress(raw, 6)).decode("ascii")
    if len(raw) > MAX_RAW_BYTES or len(packed) > MAX_COMPRESSED_BYTES:
        return {"status": "oversize"}
    table = _table(table)
    row = _fetch(table, key)
    if (row is None or row.get("state") != "pending"
            or row.get("owner") != owner or float(row.get("lease_until", 0)) <= when):
        raise CacheStoreUnavailable("Private cache publish lease mismatch")
    stamp = f"raw_{key}_{uuid.uuid4().hex}"
    body = {"PartitionKey": PARTITION, "RowKey": stamp,
            "source_key": key, "parser_version": str(parser_version)[:40],
            "fetched_at": when, "digest": hashlib.sha256(raw).hexdigest(),
            "body": packed, "state": "raw"}
    latest = {"PartitionKey": PARTITION, "RowKey": key, "state": "ready",
              "parser_version": str(parser_version)[:40], "fetched_at": when,
              "digest": body["digest"], "body": packed,
              "owner": "", "lease_until": 0}
    try:
        table.create_entity(body)
        _write(table, key, row, latest)
    except Exception as exc:
        raise CacheStoreUnavailable("Private cache immutable write or CAS failed") from exc
    return {"status": "stored", "digest": body["digest"]}
