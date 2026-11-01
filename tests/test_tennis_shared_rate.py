"""Offline ETag/CAS regressions for distributed Tennis API pacing."""
import json
import threading
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest

from tbt.providers.shared_rate import (
    MIN_GAP, plan_pace, reserve_pace, SharedRateBusy, SharedRateUnavailable
)


class Conflict(Exception):
    status_code = 412


class Missing(Exception):
    status_code = 404


class Row(dict):
    def __init__(self, value, etag):
        super().__init__(value)
        self.metadata = {"etag": str(etag)}


class Table:
    def __init__(self):
        self.lock = threading.Lock()
        self.row = None
        self.etag = 0
    def get_entity(self, **kw):
        with self.lock:
            if self.row is None:
                raise Missing()
            return Row(self.row.copy(), self.etag)
    def create_entity(self, entity):
        with self.lock:
            if self.row is not None:
                raise Conflict()
            self.row = entity.copy()
            self.etag += 1
    def update_entity(self, entity, *, etag, **kwargs):
        with self.lock:
            if str(self.etag) != str(etag):
                raise Conflict()
            self.row = entity.copy()
            self.etag += 1


def test_global_slots_are_spaced_at_six_per_second():
    t = Table()
    start = 1793560000.0
    for i in range(6):
        proof = reserve_pace(table=t, now=start + i * (MIN_GAP + 0.00001))
        assert proof["max_rps"] == 6
    with pytest.raises(SharedRateBusy):
        reserve_pace(table=t, now=start + 5 * (MIN_GAP + 0.00001) + 0.02)
    assert len(json.loads(t.row["payload"])) == 2


def test_concurrent_clients_receive_only_one_slot_at_same_instant():
    t = Table()
    now = 1793560000.0
    def attempt(_):
        try:
            reserve_pace(table=t, now=now)
            return "granted"
        except SharedRateBusy:
            return "busy"
    with ThreadPoolExecutor(max_workers=12) as pool:
        result = list(pool.map(attempt, range(12)))
    assert result.count("granted") == 1
    assert result.count("busy") == 11


def test_unavailable_or_corrupt_coordinator_fails_closed():
    class Failed:
        def get_entity(self, **kw):
            raise TimeoutError()
    with pytest.raises(SharedRateUnavailable):
        reserve_pace(table=Failed(), now=1793560000)
    t = Table()
    t.row = {"payload": json.dumps({"schema": 19, "last": 1793560000})}
    t.etag = 1
    with pytest.raises(SharedRateUnavailable):
        reserve_pace(table=t, now=1793560001)


def test_future_pace_timestamp_and_missing_cas_are_blocked():
    with pytest.raises(SharedRateUnavailable):
        plan_pace({"schema": 1, "last": 1793560010}, now=1793560000)
    class NoEtag(Table):
        def get_entity(self, **kw):
            row = super().get_entity(**kw)
            row.metadata = {}
            return row
    t = NoEtag()
    t.row = {"payload": json.dumps({"schema": 1, "last": 1793559990})}
    t.etag = 1
    with pytest.raises(SharedRateUnavailable):
        reserve_pace(table=t, now=1793560000)
