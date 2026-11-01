"""Private raw cache: cross-process reuse, integrity and paid-call avoidance."""
import concurrent.futures
import os
import sqlite3
import tempfile
import threading
from pathlib import Path

import pytest

from tbt.services.tennis_response_cache import (
    RawResponseCache, RawCacheUnavailable, cache_identity,
)
from tbt.providers.statistics import parse_statistics


def store(tmp_path):
    return RawResponseCache(tmp_path / "private-raw.sqlite")


def load(cache, loader, **kw):
    return cache.get_or_load(
        provider="tennisapi1", host="tennisapi1.p.rapidapi.com",
        endpoint="/api/tennis/event/7115726/statistics",
        kind="finished_statistics", parser_version="3", loader=loader, **kw
    )


def test_cross_instance_replay_and_parser_upgrade_without_paid_call(tmp_path):
    old, new = store(tmp_path), store(tmp_path)
    payload = {"statistics": [{"period": "ALL", "groups": [
        {"statisticsItems": [{"key": "aces", "home": "4", "away": "7"}]}
    ]}]}
    attempts = []
    def paid():
        attempts.append("paid")
        return payload
    assert load(old, paid) == payload
    actual = new.get_or_load(
        provider="tennisapi1", host="tennisapi1.p.rapidapi.com",
        endpoint="/api/tennis/event/7115726/statistics",
        kind="finished_statistics", parser_version="4",
        loader=lambda: pytest.fail("replay must not call API"),
    )
    assert parse_statistics(actual, home_is_player1=True)["p1_aces"] == 4
    assert attempts == ["paid"]
    with sqlite3.connect(old.path) as db:
        rows = db.execute("SELECT fetched_at, parser_version, digest FROM raw_history").fetchall()
    assert len(rows) == 1 and rows[0][1] == "3"


def test_credentials_rejected_and_parameter_order_normalized():
    a, _ = cache_identity("tennisapi1", "Example.test", "/event/1", {"page": 0, "season": 2026})
    b, _ = cache_identity("TENNISAPI1", "example.test", "/event/1", {"season": 2026, "page": 0})
    assert a == b
    for params in ({"api_key": "secret"}, {"authorization": "secret"}, {"token": "secret"}):
        with pytest.raises(ValueError):
            cache_identity("tennisapi1", "example.test", "/event/1", params)
    with pytest.raises(ValueError):
        cache_identity("tennisapi1", "example.test", "/event/1?api_key=secret")


def test_live_odds_never_cached(tmp_path):
    cache = store(tmp_path)
    paid = []
    for _ in range(2):
        assert cache.get_or_load(provider="tennisapi1", host="example.test",
            endpoint="/api/tennis/live/odds", kind="live_odds",
            loader=lambda: paid.append(1) or {"price": len(paid)}) == {"price": len(paid)}
    assert len(paid) == 2
    with sqlite3.connect(cache.path) as db:
        assert db.execute("SELECT count(*) FROM responses").fetchone()[0] == 0


def test_corrupted_raw_fails_closed(tmp_path):
    cache = store(tmp_path)
    load(cache, lambda: {"statistics": [1]})
    with sqlite3.connect(cache.path) as db:
        db.execute("UPDATE responses SET body='{}'")
    with pytest.raises(RawCacheUnavailable, match="integrity"):
        load(cache, lambda: pytest.fail("corrupt response must not be used"))


def test_concurrent_clients_singleflight(tmp_path):
    one, two = store(tmp_path), store(tmp_path)
    barrier = threading.Barrier(2)
    count = []
    def fetch(cache):
        barrier.wait()
        def paid():
            import time
            count.append(1)
            time.sleep(0.18)
            return {"statistics": [{"period": "ALL", "groups": []}]}
        return load(cache, paid)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(fetch, c) for c in (one, two)]
        assert [f.result(timeout=10) for f in futures] == [
            {"statistics": [{"period": "ALL", "groups": []}]}] * 2
    assert len(count) == 1


def test_missing_mount_fails_closed(tmp_path):
    with pytest.raises(RawCacheUnavailable, match="not mounted"):
        RawResponseCache(tmp_path / "absent" / "raw.sqlite")
