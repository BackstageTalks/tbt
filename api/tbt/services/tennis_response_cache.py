"""Private, source-scoped raw Tennis API cache, independent of canonical CDB.

The containing directory MUST be a private persistent volume to survive runners.
The store never issues provider requests itself and never contains credentials.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit


class RawCacheUnavailable(RuntimeError):
    """Fail closed when a configured private cache cannot coordinate safely."""


# Finished-match statistics can be revalidated on a later paid run. A live
# market is never served from disk. Caller supplies a stricter max_age when
# the event is not yet independently confirmed finished.
MAX_AGE = {
    "finished_statistics": 30 * 86400,
    "finished_detail": 86400,
    "historical_calendar": 86400,
    "live_odds": 0,
}


def cache_identity(provider: str, host: str, endpoint: str, params=None) -> tuple[str, str]:
    """Stable identity without secrets or credential-bearing URLs."""
    if not provider or not host or not endpoint.startswith("/") or urlsplit(endpoint).query:
        raise ValueError("Cache requires provider, host and a query-free endpoint")
    if "@" in host or "/" in host or "?" in host:
        raise ValueError("Invalid provider host")
    parameters = dict(params or {})
    if any(re.search(r"token|secret|password|authorization|(?:^|_)api[_-]?key", str(k), re.I)
           for k in parameters):
        raise ValueError("Credentials must not enter cache parameters")
    canonical = json.dumps(parameters, sort_keys=True, ensure_ascii=True,
                           separators=(",", ":"), allow_nan=False)
    identity = json.dumps([provider.lower(), host.lower(), endpoint, parameters],
                          sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(identity.encode()).hexdigest(), canonical


class RawResponseCache:
    def __init__(self, path):
        path = Path(path)
        if not path.parent.is_dir():
            raise RawCacheUnavailable("Private cache directory is not mounted")
        self.path = str(path)
        self.metrics = {"cache_hits": 0, "upstream_loads": 0, "inflight_wait_polls": 0,
                        "negative_not_cached": 0}
        try:
            with self._connect() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS responses (
                        key TEXT PRIMARY KEY, provider TEXT NOT NULL,
                        host TEXT NOT NULL, endpoint TEXT NOT NULL,
                        params TEXT NOT NULL, fetched_at REAL NOT NULL,
                        parser_version TEXT NOT NULL, digest TEXT NOT NULL,
                        body TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS raw_history (
                        key TEXT NOT NULL, fetched_at REAL NOT NULL,
                        parser_version TEXT NOT NULL, digest TEXT NOT NULL,
                        body TEXT NOT NULL,
                        PRIMARY KEY (key, fetched_at)
                    );
                    CREATE TABLE IF NOT EXISTS leases (
                        key TEXT PRIMARY KEY, owner TEXT NOT NULL,
                        expires_at REAL NOT NULL
                    );
                """)
        except sqlite3.Error as exc:
            raise RawCacheUnavailable("Private cache initialization failed") from exc
        try:
            Path(self.path).chmod(0o600)
        except OSError as exc:
            raise RawCacheUnavailable("Private cache permissions could not be secured") from exc

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10.0)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _lookup(self, key, max_age, now):
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT fetched_at, digest, body FROM responses WHERE key=?", (key,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise RawCacheUnavailable("Private cache read failed") from exc
        if row is None or now - row[0] >= max_age or now < row[0]:
            return None
        if hashlib.sha256(row[2].encode()).hexdigest() != row[1]:
            raise RawCacheUnavailable("Private cache integrity mismatch")
        try:
            return json.loads(row[2])
        except (ValueError, TypeError) as exc:
            raise RawCacheUnavailable("Private cache JSON corruption") from exc

    def get_or_load(self, *, provider, host, endpoint, params=None,
                    kind="finished_statistics", parser_version="unknown",
                    loader, max_age=None, wait_seconds=15.0):
        if kind not in MAX_AGE:
            raise ValueError("Unknown cache freshness class")
        ttl = MAX_AGE[kind] if max_age is None else min(MAX_AGE[kind], max_age)
        if ttl <= 0:
            # Live odds never use stale disk material or persist response bodies.
            return loader()
        key, canonical = cache_identity(provider, host, endpoint, params)
        owner = uuid.uuid4().hex
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while True:
            now = time.time()
            cached = self._lookup(key, ttl, now)
            if cached is not None:
                self.metrics["cache_hits"] += 1
                return cached
            try:
                with self._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    active = db.execute(
                        "SELECT owner, expires_at FROM leases WHERE key=?", (key,)
                    ).fetchone()
                    if not active or active[1] <= now:
                        db.execute(
                            "INSERT OR REPLACE INTO leases VALUES (?, ?, ?)",
                            (key, owner, now + 900.0)
                        )
                        granted = True
                    else:
                        granted = False
            except sqlite3.Error as exc:
                raise RawCacheUnavailable("Private cache lease unavailable") from exc
            if granted:
                break
            if time.monotonic() >= deadline:
                raise RawCacheUnavailable("Concurrent raw request still in flight")
            self.metrics["inflight_wait_polls"] += 1
            time.sleep(0.1)
        try:
            # Check again after claiming; a prior owner may have completed
            # between the initial read and this lease acquisition.
            existing = self._lookup(key, ttl, time.time())
            if existing is not None:
                self.metrics["cache_hits"] += 1
                return existing
            self.metrics["upstream_loads"] += 1
            result = loader()
            if not isinstance(result, (dict, list)):
                raise RawCacheUnavailable("Only JSON objects/arrays are cacheable")
            # Empty statistics from 200 responses are not durable coverage
            # evidence. Preserve normal provider cooldown instead of replaying
            # a 30-day false miss.
            event = (result.get("event", result) if isinstance(result, dict) else {})
            if kind == "finished_detail" and (
                    not isinstance(event, dict)
                    or not isinstance(event.get("status"), dict)
                    or event["status"].get("type") != "finished"):
                self.metrics["negative_not_cached"] += 1
                return result
            if kind == "finished_statistics" and (not isinstance(result, dict)
                    or not result.get("statistics")):
                self.metrics["negative_not_cached"] += 1
                return result
            body = json.dumps(result, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True, allow_nan=False)
            digest = hashlib.sha256(body.encode()).hexdigest()
            fetched_at = time.time()
            try:
                with self._connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    current = db.execute(
                        "SELECT owner FROM leases WHERE key=?", (key,)
                    ).fetchone()
                    if not current or current[0] != owner:
                        raise RawCacheUnavailable("Raw cache lease ownership lost")
                    db.execute("INSERT INTO raw_history VALUES (?, ?, ?, ?, ?)",
                               (key, fetched_at, str(parser_version), digest, body))
                    db.execute("""INSERT OR REPLACE INTO responses
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (key, provider, host, endpoint, canonical, fetched_at,
                         str(parser_version), digest, body))
            except sqlite3.Error as exc:
                raise RawCacheUnavailable("Raw cache persist failed") from exc
            return result
        finally:
            try:
                with self._connect() as db:
                    db.execute("DELETE FROM leases WHERE key=? AND owner=?", (key, owner))
            except sqlite3.Error:
                # Next request fails closed until lease expiry; never launch
                # uncoordinated duplicate requests on storage failure.
                pass
