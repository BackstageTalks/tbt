"""Warm serving snapshot: validated source reuse, fresh authority and source isolation."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

import function_app as api
from tbt.services import feed as serving


def _snapshot(event="event-a"):
    return {
        "schema": 1,
        "ready": True,
        "generated_at": "2026-11-13T05:00:00Z",
        "upcoming": [{
            "event_id": event, "scheduled_at": "2026-11-13T15:00:00Z",
            "player1": {"id": "p1", "name": "Alpha"},
            "player2": {"id": "p2", "name": "Beta"},
        }],
        "results": [{
            "event_id": event, "scheduled_at": "2026-11-11T15:00:00Z",
            "player1": {"id": "p1", "name": "Alpha", "rank": {"history": [7, 8]}},
            "player2": {"id": "p2", "name": "Beta"},
            "result": {"winner_id": "p1"},
            "market_publications": [{
                "section": "top_daily", "market": "match_winner",
                "selection_id": "p1", "issued_at": "2026-11-11T06:00:00Z",
                "result": {"correct": True, "profit_units": 0.5},
            }],
        }],
        "top_daily_picks": [],
        "prime_picks": [],
        "value_picks": [],
        "ace_picks": [],
        "sg_picks": [],
    }


def _file(tmp_path, event="event-a"):
    path = tmp_path / "feed.json"
    path.write_text(json.dumps(_snapshot(event)), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def clean_source_cache():
    serving._validated_serving_source.cache_clear()
    yield
    serving._validated_serving_source.cache_clear()


def test_unchanged_validated_release_reads_once_and_keeps_identity(monkeypatch, tmp_path):
    path = _file(tmp_path)
    original = serving.read_feed
    calls = []

    def observed(p):
        calls.append(Path(p))
        return original(p)

    monkeypatch.setattr(serving, "read_feed", observed)
    first = serving.read_serving_source_cached(path)
    second = serving.read_serving_source_cached(path)
    assert first is second
    assert len(calls) == 1
    assert serving._validated_serving_source.cache_info().hits == 1
    assert serving._validated_serving_source.cache_info().misses == 1
    assert first == original(path)


def test_rewrite_and_atomic_replacement_immediately_invalidate_source(tmp_path):
    path = _file(tmp_path)
    before = serving.read_serving_source_cached(path)
    # An ordinary write invalidates the mtime/ctime metadata revision.
    path.write_text(json.dumps(_snapshot("event-b")), encoding="utf-8")
    after = serving.read_serving_source_cached(path)
    assert after is not before
    assert after["results"][0]["event_id"] == "event-b"
    # An atomic deployed file replacement must not keep a stale snapshot.
    replacement = tmp_path / "replacement.json"
    replacement.write_text(json.dumps(_snapshot("event-c")), encoding="utf-8")
    replacement.replace(path)
    latest = serving.read_serving_source_cached(path)
    assert latest is not after
    assert latest["results"][0]["event_id"] == "event-c"


def test_invalid_or_oversize_replacement_never_serves_stale_cached_success(tmp_path, monkeypatch):
    path = _file(tmp_path)
    cached = serving.read_serving_source_cached(path)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid serving feed JSON"):
        serving.read_serving_source_cached(path)
    path.write_text(json.dumps(_snapshot("event-b")), encoding="utf-8")
    monkeypatch.setattr(serving, "MAX_FEED_BYTES", 100)
    with pytest.raises(ValueError, match="Serving feed exceeds"):
        serving.read_serving_source_cached(path)
    assert cached["results"][0]["event_id"] == "event-a"


def test_removed_file_keeps_original_empty_feed_semantics(tmp_path):
    path = _file(tmp_path)
    serving.read_serving_source_cached(path)
    path.unlink()
    assert serving.read_serving_source_cached(path) == serving.empty_feed()


def test_cached_source_is_not_mutated_by_member_and_results_processing(monkeypatch, tmp_path):
    path = _file(tmp_path)
    monkeypatch.setattr(api, "FEED", path)
    monkeypatch.setattr(api, "CONFIRMED_ACE_OU", tmp_path / "absent.json")
    monkeypatch.setattr(api, "load_authority", lambda _day: None)
    cached = api._read_feed_with_confirmed_aces_ou(reuse_source=True)
    before = deepcopy(cached)
    public = api._visible_issued_feed(cached)
    assert public is not cached
    # Source Results are independently detached by the settlement and
    # entitlement gates, including the nested market publication and players.
    settled = api.merge_settled_results(public, [])
    member, manifest = api.filter_feed_for_access(
        settled, {"id": "member-a", "status": "active",
                  "plan": "admin", "role": "admin"}, {},
    )
    assert manifest["plan"] == "admin"
    assert member["results"]
    member["results"][0]["player1"]["rank"]["history"].append(99)
    member["results"][0]["market_publications"][0]["result"]["correct"] = False
    assert cached == before
    assert api._read_feed_with_confirmed_aces_ou(reuse_source=True) is cached
    other, _ = api.filter_feed_for_access(
        api.merge_settled_results(api._visible_issued_feed(cached), []),
        {"id": "member-b", "status": "active",
         "plan": "admin", "role": "admin"}, {},
    )
    assert other["results"][0]["player1"]["rank"]["history"] == [7, 8]
    assert other["results"][0]["market_publications"][0]["result"]["correct"] is True


def test_dynamic_ace_issuance_sidecar_is_reloaded_even_when_base_is_cached(monkeypatch, tmp_path):
    path = _file(tmp_path)
    sidecar = tmp_path / "confirmed.json"
    sidecar.write_text(json.dumps({"schema": 1, "issued_aces_ou": [], "revision": 1}), encoding="utf-8")
    monkeypatch.setattr(api, "FEED", path)
    monkeypatch.setattr(api, "CONFIRMED_ACE_OU", sidecar)
    monkeypatch.setattr(api, "attach_confirmed_aces_ou_sidecar",
                        lambda base, data: {**base, "receipt_revision": data["revision"]})
    first = api._read_feed_with_confirmed_aces_ou(reuse_source=True)
    sidecar.write_text(json.dumps({"schema": 1, "issued_aces_ou": [], "revision": 2}), encoding="utf-8")
    second = api._read_feed_with_confirmed_aces_ou(reuse_source=True)
    assert first["receipt_revision"] == 1
    assert second["receipt_revision"] == 2
    assert second["results"] is first["results"]  # Only validated base is cached.
