"""Detached Results fast path avoids redundant copies without changing grants."""
from copy import deepcopy

import pytest
from tbt.services import entitlements as access


def _row(number=1):
    return {
        "event_id": f"event-{number}",
        "scheduled_at": "2026-11-11T15:00:00+00:00",
        "player1": {"id": "a", "name": "A", "details": {"depth": 17}},
        "player2": {"id": "b", "name": "B"},
        "market_publications": [
            {
                "section": "top_daily", "market": "match_winner",
                "selection_id": "a", "issued_at": "2026-11-11T07:00:00Z",
                "betting_day": "2026-11-11", "offer_position": number,
                "result": {"correct": True, "profit_units": 1.2},
            },
            {"section": "internal_only", "market": "internal", "value": "private"},
        ],
    }


def _manifest(plan):
    return {
        "plan": plan, "result_categories": ["top_daily"],
        "sections": {"daily": {
            "enabled": True, "display_state": "active",
            "visible_picks": "ALL", "row_overrides": {},
        }},
    }


def test_public_reference_fast_path_keeps_direct_public_helper_detached():
    row = _row()
    borrowed = access._public_result_publication_refs(row)
    independent = access._public_result_publications(row)
    assert len(borrowed) == len(independent) == 1
    assert borrowed[0] is row["market_publications"][0]
    assert independent[0] == borrowed[0]
    assert independent[0] is not borrowed[0]


@pytest.mark.parametrize("plan", ["elite", "legend", "goat"])
def test_detached_member_and_day_gates_do_not_repeat_deepcopy(monkeypatch, plan):
    raw = [_row(1), _row(2)]
    preserved = deepcopy(raw)
    # Initial public-category gate remains the only source-isolation copy.
    detached = access._filter_result_history(raw, None, allowed_categories={"top_daily"})
    assert len(detached) == 2
    original_deepcopy = access.deepcopy
    calls = []

    def count_deepcopy(value):
        calls.append(value)
        return original_deepcopy(value)

    monkeypatch.setattr(access, "deepcopy", count_deepcopy)
    manifest = _manifest(plan)
    access_context = {"id": "member-1", "plan": plan}
    member_rows = access.filter_results_for_member_limits(
        detached, manifest, access_context, already_detached=True,
    )
    final_rows = access.filter_results_for_issued_day(
        member_rows, manifest, already_detached=True,
    )
    assert len(final_rows) == 2
    assert not calls, "No unnecessary copying after the initial source isolation"
    assert final_rows[0]["market_publications"][0]["section"] == "top_daily"
    assert "internal_only" not in str(final_rows)
    # Downstream formatting may edit independent authorized rows but never raw.
    final_rows[0]["player1"]["details"]["depth"] = 1
    final_rows[0]["market_publications"][0]["result"]["correct"] = False
    assert raw == preserved


@pytest.mark.parametrize("plan", ["elite", "legend", "goat"])
def test_legacy_helper_calls_still_copy_data_independently(plan):
    source = access._filter_result_history([_row()], None, allowed_categories={"top_daily"})
    manifest = _manifest(plan)
    access_context = {"id": "member-1", "plan": plan}
    independent = access.filter_results_for_member_limits(
        source, manifest, access_context,
    )
    after_day_gate = access.filter_results_for_issued_day(
        independent, manifest,
    )
    assert len(after_day_gate) == 1
    assert independent[0]["player1"] is not source[0]["player1"]
    assert after_day_gate[0]["player1"] is not independent[0]["player1"]
    assert independent[0]["market_publications"][0] is not source[0]["market_publications"][0]
    assert after_day_gate[0]["market_publications"][0] is not independent[0]["market_publications"][0]


def test_authorized_member_flow_uses_fast_path_only_after_first_result_copy():
    from pathlib import Path
    code = (Path(__file__).resolve().parents[1] / "api/tbt/services/entitlements.py").read_text()
    first = code.index('result["results"] = _filter_result_history(')
    second = code.index('result["results"] = filter_results_for_member_limits(')
    third = code.index('result["results"] = filter_results_for_issued_day(')
    assert first < second < third
    assert code[second:third].count('already_detached=True') == 1
    assert 'already_detached=True' in code[third:third+170]
