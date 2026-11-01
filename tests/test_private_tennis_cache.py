"""Private Azure raw cache: CAS leases, immutable replay, integrity and no overwrite."""
import json
import threading
import uuid

import pytest

from tbt.services.private_tennis_cache import (
    claim, read, publish, abort, CacheStoreUnavailable,
)


class Missing(Exception):
    status_code = 404


class Conflict(Exception):
    status_code = 412


class Row(dict):
    def __init__(self, item, etag):
        super().__init__(item)
        self.metadata = {"etag": str(etag)}


class FakeTable:
    def __init__(self):
        self.items = {}
        self.lock = threading.Lock()
        self.etag = 0

    def get_entity(self, partition_key, row_key):
        with self.lock:
            if row_key not in self.items:
                raise Missing()
            return Row(self.items[row_key][0].copy(), self.items[row_key][1])

    def create_entity(self, entity):
        with self.lock:
            key = entity["RowKey"]
            if key in self.items:
                raise Conflict()
            self.etag += 1
            self.items[key] = (entity.copy(), self.etag)

    def update_entity(self, entity, *, etag, **kw):
        with self.lock:
            key = entity["RowKey"]
            if key not in self.items or str(self.items[key][1]) != str(etag):
                raise Conflict()
            self.etag += 1
            self.items[key] = ({**self.items[key][0], **entity}, self.etag)


KEY = "a" * 64
OWNER = "b" * 32
OTHER = "c" * 32


def test_private_cache_replay_and_immutable_source_history():
    table = FakeTable()
    payload = {"statistics": [{"period": "ALL", "groups": [
        {"statisticsItems": [{"key": "aces", "home": "7", "away": "2"}]}
    ]}]}
    assert claim(KEY, OWNER, max_age=86400, table=table, now=1000)["status"] == "claimed"
    assert claim(KEY, OTHER, max_age=86400, table=table, now=1001)["status"] == "busy"
    assert publish(KEY, OWNER, payload, "3", table=table, now=1002)["status"] == "stored"
    assert read(KEY, max_age=86400, table=table, now=1003)["payload"] == payload
    assert claim(KEY, OTHER, max_age=86400, table=table, now=1004)["status"] == "hit"
    assert sum(k.startswith("raw_") for k in table.items) == 1
    assert read(KEY, max_age=86400, table=table, now=1004)["parser_version"] == "3"


def test_old_raw_replaced_only_after_expiry_and_previous_archived():
    table = FakeTable()
    first, second = {"statistics": [{"period": "ALL", "groups": []}]}, {"statistics": [1]}
    claim(KEY, OWNER, max_age=100, table=table, now=1000)
    publish(KEY, OWNER, first, "3", table=table, now=1001)
    assert claim(KEY, OTHER, max_age=100, table=table, now=1110)["status"] == "claimed"
    publish(KEY, OTHER, second, "4", table=table, now=1111)
    assert read(KEY, max_age=100, table=table, now=1112)["payload"] == second
    assert sum(k.startswith("raw_") for k in table.items) == 2


def test_corrupt_private_cache_and_mismatched_lease_fail_closed():
    table = FakeTable()
    claim(KEY, OWNER, max_age=100, table=table, now=1000)
    with pytest.raises(CacheStoreUnavailable, match="lease mismatch"):
        publish(KEY, OTHER, {}, "3", table=table, now=1001)
    with pytest.raises(CacheStoreUnavailable, match="mismatch"):
        abort(KEY, OTHER, table=table)
    publish(KEY, OWNER, {"stat": 1}, "3", table=table, now=1001)
    data, etag = table.items[KEY]
    table.items[KEY] = ({**data, "digest": "0"*64}, etag)
    with pytest.raises(CacheStoreUnavailable, match="integrity"):
        read(KEY, max_age=86400, table=table, now=1002)


def test_cached_absence_lease_abort_and_fresh_claim():
    table = FakeTable()
    assert claim(KEY, OWNER, max_age=100, table=table, now=1000)["status"] == "claimed"
    assert abort(KEY, OWNER, table=table)["status"] == "aborted"
    assert read(KEY, max_age=100, table=table, now=1001)["status"] == "miss"
    assert claim(KEY, OTHER, max_age=100, table=table, now=1002)["status"] == "claimed"


def test_independent_remote_clients_reuse_paid_body_without_new_provider_call(monkeypatch):
    from tbt.services.tennis_remote_cache_client import HttpRawResponseCache
    from tbt.services.private_tennis_cache import read, claim, publish, abort
    backend = FakeTable()
    class Response:
        status_code = 200
        def __init__(self, value):
            self.value = value
        def json(self):
            return {"ok": True, **self.value}
    def fake_request(method, url, *, params=None, json=None, headers=None):
        assert headers == {"X-Blinq-Worker-Token": "synthetic-worker"}
        data = json or {}
        if method == "GET":
            result = read(params["key"], max_age=float(params["max_age"]), table=backend, now=1002)
        elif data["action"] == "claim":
            result = claim(data["key"], data["owner"], max_age=data["max_age"], table=backend, now=1000)
        elif data["action"] == "publish":
            result = publish(data["key"], data["owner"], data["payload"], data["parser_version"],
                             table=backend, now=1001)
        elif data["action"] == "abort":
            result = abort(data["key"], data["owner"], table=backend)
        else:
            raise AssertionError("Unexpected authenticated action")
        return Response(result)
    first = HttpRawResponseCache("https://example.test/api/v1/internal/tennis-raw-cache",
                                 "synthetic-worker")
    second = HttpRawResponseCache("https://example.test/api/v1/internal/tennis-raw-cache",
                                  "synthetic-worker")
    monkeypatch.setattr(first.client, "request", fake_request)
    monkeypatch.setattr(second.client, "request", fake_request)
    paid = []
    data = {"statistics": [{"period": "ALL", "groups": []}]}
    def loader():
        paid.append(1)
        return data
    base = {"provider": "tennisapi1", "host": "tennisapi1.p.rapidapi.com",
            "endpoint": "/api/tennis/event/7115726/statistics", "kind": "finished_statistics",
            "parser_version": "3"}
    assert first.get_or_load(loader=loader, **base) == data
    assert second.get_or_load(loader=lambda: pytest.fail("Duplicate paid request"), **base) == data
    assert len(paid) == 1
    assert second.metrics["cache_hits"] == 1
    first.close()
    second.close()


def test_remote_token_never_sent_to_untrusted_service_origin(monkeypatch):
    from tbt.services.tennis_remote_cache_client import HttpRawResponseCache
    from tbt.services.tennis_response_cache import RawCacheUnavailable
    monkeypatch.setenv(
        "BLINQ_SHARED_API_BUDGET_URL",
        "https://trusted.azurestaticapps.net/api/v1/internal/api-budget/reserve",
    )
    with pytest.raises(RawCacheUnavailable, match="verified budget origin"):
        HttpRawResponseCache("https://attacker.test/api/v1/internal/tennis-raw-cache",
                             "secret-worker-token")
    allowed = HttpRawResponseCache(
        "https://trusted.azurestaticapps.net/api/v1/internal/tennis-raw-cache",
        "secret-worker-token",
    )
    allowed.close()
