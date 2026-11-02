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



class PublishBetweenClaimReads(FakeTable):
    """Publish another worker's result after the first missing-row snapshot."""
    def __init__(self):
        super().__init__()
        self.injected = False
        self.payload = {"statistics": [{"period": "ALL", "groups": []}]}

    def get_entity(self, partition_key, row_key):
        if not row_key.startswith("raw_") and not self.injected:
            self.injected = True
            assert claim(row_key, OTHER, max_age=3600, table=self, now=1000)["status"] == "claimed"
            assert publish(row_key, OTHER, self.payload, "3", table=self, now=1001)["status"] == "stored"
            raise Missing()
        return super().get_entity(partition_key, row_key)


def test_interleaved_publish_is_integrity_checked_hit_not_second_claim():
    backend = PublishBetweenClaimReads()
    result = claim(KEY, OWNER, max_age=3600, table=backend, now=1002)
    assert result["status"] == "hit"
    assert result["payload"] == backend.payload
    assert result["parser_version"] == "3"
    assert read(KEY, max_age=3600, table=backend, now=1003)["status"] == "hit"
    assert sum(k.startswith("raw_") for k in backend.items) == 1
    assert backend.items[KEY][0]["state"] == "ready"


def test_http_claim_race_avoids_duplicate_provider_load(monkeypatch):
    from tbt.services.tennis_remote_cache_client import HttpRawResponseCache
    backend = PublishBetweenClaimReads()

    class Response:
        status_code = 200
        def __init__(self, result):
            self.result = result
        def json(self):
            return {"ok": True, **self.result}

    def fake_request(method, url, *, params=None, json=None, headers=None):
        if method == "GET":
            # A miss was seen before another worker published; race inside claim.
            return Response({"status": "miss"})
        assert method == "POST" and json["action"] == "claim"
        return Response(claim(json["key"], json["owner"], max_age=json["max_age"],
                              table=backend, now=1002))

    client = HttpRawResponseCache("https://example.test/api/v1/internal/tennis-raw-cache",
                                  "synthetic-worker")
    monkeypatch.setattr(client.client, "request", fake_request)
    try:
        result = client.get_or_load(
            provider="tennisapi1", host="tennisapi1.p.rapidapi.com",
            endpoint="/api/tennis/event/7115726/statistics",
            parser_version="3", loader=lambda: pytest.fail("Duplicate paid provider request"),
        )
        assert result == backend.payload
        assert client.metrics["cache_hits"] == 1
        assert client.metrics["upstream_loads"] == 0
    finally:
        client.close()


def test_two_simultaneous_clients_share_single_provider_load(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from time import sleep
    from tbt.services.tennis_remote_cache_client import HttpRawResponseCache
    from tbt.services.tennis_response_cache import cache_identity
    backend = FakeTable()
    first_reads = threading.Barrier(2)
    lock = threading.Lock()
    initial_reads = 0
    paid_calls = 0
    payload = {"statistics": [{"period": "ALL", "groups": []}]}

    class Response:
        status_code = 200
        def __init__(self, value):
            self.value = value
        def json(self):
            return {"ok": True, **self.value}

    def fake_request(method, url, *, params=None, json=None, headers=None):
        nonlocal initial_reads
        assert headers == {"X-Blinq-Worker-Token": "synthetic-worker"}
        if method == "GET":
            with lock:
                initial_reads += 1
                initial = initial_reads <= 2
            if initial:
                first_reads.wait(timeout=5)
            value = read(params["key"], max_age=float(params["max_age"]),
                         table=backend, now=1002)
        elif json["action"] == "claim":
            value = claim(json["key"], json["owner"], max_age=json["max_age"],
                          table=backend, now=1000)
        elif json["action"] == "publish":
            value = publish(json["key"], json["owner"], json["payload"],
                            json["parser_version"], table=backend, now=1001)
        elif json["action"] == "abort":
            value = abort(json["key"], json["owner"], table=backend)
        else:
            raise AssertionError("Unexpected cache request")
        return Response(value)

    def task(_):
        nonlocal paid_calls
        client = HttpRawResponseCache("https://example.test/api/v1/internal/tennis-raw-cache",
                                      "synthetic-worker")
        monkeypatch.setattr(client.client, "request", fake_request)
        def loader():
            nonlocal paid_calls
            with lock:
                paid_calls += 1
            sleep(0.08)
            return payload
        try:
            value = client.get_or_load(
                provider="tennisapi1", host="tennisapi1.p.rapidapi.com",
                endpoint="/api/tennis/event/7115726/statistics", parser_version="3",
                loader=loader, wait_seconds=3,
            )
            return value, client.metrics.copy()
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        out = list(pool.map(task, range(2)))
    assert all(v == payload for v, _ in out)
    assert paid_calls == 1
    assert sum(m["upstream_loads"] for _, m in out) == 1
    assert sum(m["cache_hits"] for _, m in out) == 1
    assert sum(k.startswith("raw_") for k in backend.items) == 1


def test_corrupt_ready_snapshot_in_claim_fails_closed():
    backend = FakeTable()
    assert claim(KEY, OWNER, max_age=3600, table=backend, now=1000)["status"] == "claimed"
    publish(KEY, OWNER, {"statistics": [1]}, "3", table=backend, now=1001)
    body, etag = backend.items[KEY]
    backend.items[KEY] = ({**body, "digest": "f" * 64}, etag)
    with pytest.raises(CacheStoreUnavailable, match="integrity"):
        claim(KEY, OTHER, max_age=3600, table=backend, now=1002)
    assert backend.items[KEY][0]["state"] == "ready"
