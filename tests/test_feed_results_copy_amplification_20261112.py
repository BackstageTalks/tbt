"""Regression proof: only redundant Results copies are removed, not access gates."""
from copy import deepcopy

import pytest
from tbt.services import entitlements as access


def _publication(section, market, selection):
    return {
        "section": section, "market": market, "selection_id": selection,
        "issued_at": "2026-11-11T07:00:00Z",
        "result": {"correct": True, "staked_units": 1, "profit_units": 1},
    }


def test_public_results_projection_copies_authorized_data_once(monkeypatch):
    eligible = _publication("top_daily", "match_winner", "allowed")
    private = _publication("internal_research", "private_market", "secret")
    other = _publication("value", "match_winner", "value")
    source = [{
        "event_id": "match-1", "scheduled_at": "2026-11-11T10:00:00Z",
        "player1": {"name": "A", "model": {"confidence": 0.7}},
        "market_publications": [eligible, private, other],
    }]
    before = deepcopy(source)
    calls = []
    original = deepcopy

    def traced(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(access, "deepcopy", traced)
    result = access._filter_result_history(
        source, None, allowed_categories={"top_daily"}
    )
    assert len(calls) == 1, "Only one deep copy per included Results row"
    assert result[0]["market_publications"] == [eligible]
    assert result[0]["player1"] == source[0]["player1"]
    assert result[0]["player1"] is not source[0]["player1"]
    assert result[0]["market_publications"][0] is not eligible
    result[0]["market_publications"][0]["result"]["correct"] = False
    result[0]["player1"]["model"]["confidence"] = 0.1
    assert source == before
    assert all(p.get("selection_id") != "secret" for p in result[0]["market_publications"])


def test_other_public_market_and_empty_invalid_rows_match_original_gate():
    rows = [
        {"event_id": "p", "market_publications": [
            _publication("unknown", "aces", "ace"), {"market": "private"}]},
        {"event_id": "q", "market_publications": [{"market": "private"}]},
        {"event_id": "r", "market_publications": ["bad", None]},
    ]
    result = access._filter_result_history(rows, None)
    assert [row["event_id"] for row in result] == ["p"]
    assert result[0]["market_publications"][0]["selection_id"] == "ace"


@pytest.mark.parametrize("plan", ["admin", "legend", "goat"])
def test_full_history_issued_gate_default_isolated_but_detached_fast_path(plan):
    row = {"event_id": "r", "market_publications": [_publication("ace", "aces", "a")]}
    rows = [row]
    manifest = {"plan": plan}
    independent = access.filter_results_for_issued_day(rows, manifest)
    assert independent == rows and independent is not rows
    assert independent[0] is not row
    detached = access.filter_results_for_issued_day(rows, manifest, already_detached=True)
    assert detached is rows


def test_admin_results_limit_gate_default_isolated_but_detached_fast_path():
    row = {"event_id": "r", "market_publications": [_publication("ace", "aces", "a")]}
    rows = [row]
    manifest = {"plan": "admin"}
    independent = access.filter_results_for_member_limits(rows, manifest, {"plan": "admin"})
    assert independent == rows and independent is not rows
    assert independent[0] is not row
    detached = access.filter_results_for_member_limits(
        rows, manifest, {"plan": "admin"}, already_detached=True
    )
    assert detached is rows


def test_feed_callers_only_opt_out_after_detaching_results():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    ent = (root / "api/tbt/services/entitlements.py").read_text()
    api = (root / "api/function_app.py").read_text()
    assert 'result["results"] = _filter_result_history(' in ent
    assert 'result["results"] = filter_results_for_member_limits(' in ent
    assert ent.count("already_detached=True,") >= 2
    assert 'data["results"] = filter_results_for_categories(' in api
    assert api.count("already_detached=True,") == 2
