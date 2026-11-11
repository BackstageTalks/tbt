"""Bounded CLV feed history reads: authorization, precedence, and concurrency."""
from copy import deepcopy
from threading import Barrier, Lock
import time

import pytest

from tbt.services import clv_market_history as clv


def _row(event_id, market_movement=None):
    result = {"event_id": event_id}
    if market_movement is not None:
        result["market_movement"] = market_movement
    return result


def _fallback(event_id):
    return {
        "provider": "propline",
        "verified": True,
        "exact_event_id_used": True,
        "bookmaker": f"Book-{event_id}",
        "history": [{"captured_at": "2026-11-01T10:00:00Z"}],
    }


def test_native_verified_history_never_reads_or_gets_overwritten(monkeypatch):
    native = {
        "provider": "tennisapi",
        "verified": True,
        "history": [{"captured_at": "first"}, {"captured_at": "second"}],
    }
    feed = {"top_daily_picks": [_row("1", native)],
            "daily_picks": [], "value_picks": []}
    before = deepcopy(feed)

    def fail_read(event_id):
        pytest.fail(f"unexpected Azure query for native history: {event_id}")

    monkeypatch.setattr(clv, "read_event_history", fail_read)
    assert clv.attach_offer_clv(feed) is feed
    assert feed == before


def test_only_authorized_sections_and_valid_exact_ids_are_queried(monkeypatch):
    calls = []
    monkeypatch.setattr(
        clv, "read_event_history",
        lambda event_id: calls.append(event_id) or _fallback(event_id),
    )
    feed = {
        "top_daily_picks": [_row("good"), _row("bad id")],
        "daily_picks": [_row("good"), _row("")],
        "value_picks": [_row("other")],
        "prime_picks": [_row("not-authorized-for-clv")],
        "results": [_row("result-not-in-scope")],
    }
    assert clv.attach_offer_clv(feed) is feed
    assert sorted(calls) == ["good", "other"]
    assert feed["top_daily_picks"][0]["market_movement"]["bookmaker"] == "Book-good"
    assert feed["daily_picks"][0]["market_movement"]["bookmaker"] == "Book-good"
    assert feed["value_picks"][0]["market_movement"]["bookmaker"] == "Book-other"
    assert "market_movement" not in feed["top_daily_picks"][1]
    assert "market_movement" not in feed["prime_picks"][0]
    assert "market_movement" not in feed["results"][0]


def test_native_history_on_one_alias_does_not_suppress_other_alias(monkeypatch):
    calls = []
    native = {"provider": "tennisapi", "verified": True,
              "history": [{"t": 1}, {"t": 2}]}
    feed = {"top_daily_picks": [_row("same", native)],
            "daily_picks": [_row("same")],
            "value_picks": []}
    monkeypatch.setattr(clv, "read_event_history",
                        lambda eid: calls.append(eid) or _fallback(eid))
    clv.attach_offer_clv(feed)
    assert calls == ["same"]
    assert feed["top_daily_picks"][0]["market_movement"] is native
    assert feed["daily_picks"][0]["market_movement"]["provider"] == "propline"


def test_three_independent_reads_start_concurrently(monkeypatch):
    barrier = Barrier(3, timeout=10)

    def read(event_id):
        barrier.wait()
        return _fallback(event_id)

    monkeypatch.setattr(clv, "read_event_history", read)
    feed = {"top_daily_picks": [_row("a"), _row("b"), _row("c")]}
    clv.attach_offer_clv(feed)
    assert {r["market_movement"]["bookmaker"] for r in feed["top_daily_picks"]} == {
        "Book-a", "Book-b", "Book-c"
    }


def test_concurrency_is_bounded_and_values_remain_event_isolated(monkeypatch):
    lock = Lock()
    running = 0
    peak = 0
    calls = []

    def read(event_id):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
            calls.append(event_id)
        time.sleep(0.015)
        with lock:
            running -= 1
        return _fallback(event_id)

    monkeypatch.setattr(clv, "read_event_history", read)
    feed = {"value_picks": [_row(str(i)) for i in range(12)]}
    clv.attach_offer_clv(feed)
    assert peak <= 3
    assert peak >= 2
    assert sorted(calls, key=int) == [str(i) for i in range(12)]
    assert [r["market_movement"]["bookmaker"] for r in feed["value_picks"]] == [
        f"Book-{i}" for i in range(12)
    ]


def test_storage_failure_preserves_existing_feed_and_propagates(monkeypatch):
    feed = {"top_daily_picks": [_row("a")], "value_picks": [_row("b")]}
    before = deepcopy(feed)

    def read(event_id):
        if event_id == "b":
            raise clv.AdminStorageUnavailable("CLV observation read failed")
        return _fallback(event_id)

    monkeypatch.setattr(clv, "read_event_history", read)
    with pytest.raises(clv.AdminStorageUnavailable, match="CLV observation"):
        clv.attach_offer_clv(feed)
    assert feed == before


def test_empty_missing_and_non_mapping_sections_do_not_query_storage(monkeypatch):
    monkeypatch.setattr(clv, "read_event_history",
                        lambda _: pytest.fail("unexpected query"))
    for feed in (None, {}, {"top_daily_picks": []},
                 {"top_daily_picks": "wrong", "value_picks": [None, ""]}):
        assert clv.attach_offer_clv(feed) is feed
