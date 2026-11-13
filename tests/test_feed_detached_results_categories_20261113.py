"""Authenticated Results category recheck: same grants, no duplicate nested copy."""
from copy import deepcopy
from pathlib import Path

import pytest

from tbt.services import entitlements as access


def _row():
    return {
        "event_id": "e-1",
        "scheduled_at": "2026-11-11T12:00:00+00:00",
        "player1": {"id": "p1", "name": "Alpha", "model": {"confidence": 0.71}},
        "player2": {"id": "p2", "name": "Beta"},
        "market_publications": [
            {"section": "top_daily", "market": "match_winner",
             "selection_id": "p1", "result": {"correct": True, "profit_units": 0.6}},
            {"section": "value", "market": "match_winner",
             "selection_id": "p2", "result": {"correct": False}},
            {"section": "internal_private", "market": "model_internal",
             "selection_id": "secret", "result": {"correct": True}},
        ],
    }


@pytest.mark.parametrize("categories", [
    {"top_daily"}, {"value"}, {"top_daily", "value"}, set(),
])
def test_detached_category_gate_preserves_exact_default_result_and_isolation(monkeypatch, categories):
    raw = _row()
    original = deepcopy(raw)
    # The real first entitlement gate deep-copies only authorized publications.
    authorized = access._filter_result_history(
        [raw], None, allowed_categories={"top_daily", "value"},
    )
    assert len(authorized) == 1
    assert len(authorized[0]["market_publications"]) == 2
    assert raw == original

    baseline = access.filter_results_for_categories(authorized, categories)
    calls = []
    copy = access.deepcopy

    def observed(value):
        calls.append(value)
        return copy(value)

    monkeypatch.setattr(access, "deepcopy", observed)
    fast = access.filter_results_for_categories(
        authorized, categories, already_detached=True,
    )
    assert fast == baseline, "The same categories and rows must remain visible"
    assert calls == [], "Nested public Results were already separated at authorization"
    assert all(pub.get("selection_id") != "secret"
               for row in fast for pub in row["market_publications"])
    if fast:
        assert fast[0] is not authorized[0]
        assert fast[0]["player1"] is authorized[0]["player1"]
        assert fast[0]["market_publications"] is not authorized[0]["market_publications"]
        fast[0]["player1"]["model"]["confidence"] = 0.01
        fast[0]["market_publications"][0]["result"]["correct"] = False
        assert raw == original, "Borrowed response data must never mutate issued authority"
    assert raw == original


def test_default_category_gate_remains_independently_mutable_for_direct_callers():
    raw = _row()
    before = deepcopy(raw)
    out = access.filter_results_for_categories([raw], {"top_daily"})
    assert len(out) == 1
    out[0]["player1"]["model"]["confidence"] = 0.01
    out[0]["market_publications"][0]["result"]["correct"] = False
    assert raw == before


def test_malformed_and_private_runtime_publications_are_not_leaked():
    rows = [
        {"event_id": "invalid", "market_publications": ["bad", None, {"market": "secret"}]},
        {"event_id": "m", "market_publications": [
            {"section": "internal_private", "selection_id": "private"},
            {"section": "top_daily", "market": "match_winner", "selection_id": "public"},
            {"section": "value", "market": "match_winner", "selection_id": "not-allowed"},
        ]},
    ]
    original = deepcopy(rows)
    expected = access.filter_results_for_categories(rows, {"top_daily"})
    actual = access.filter_results_for_categories(
        rows, {"top_daily"}, already_detached=True,
    )
    assert actual == expected
    assert len(actual) == 1
    assert [p["selection_id"] for p in actual[0]["market_publications"]] == ["public"]
    assert rows == original


def test_fast_path_is_only_used_after_verified_authorization():
    source = (Path(__file__).resolve().parents[1] / "api/function_app.py").read_text()
    feed = source[source.index('@app.route(route="v1/feed", methods=["GET"])'):
                  source.index('@app.route(route="v1/internal/clv-snapshot"')]
    assert feed.index("data, entitlements = filter_feed_for_access(") < feed.index(
        'data["results"] = filter_results_for_categories(')
    assert 'data.get("results") or [], entitlements.get("result_categories") or [],\n                    already_detached=True,' in feed
    for phase in ("results_categories", "results_member", "results_issued", "kpi_cards"):
        assert f'trace_stage("{phase}")' in feed
