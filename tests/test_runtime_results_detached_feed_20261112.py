"""Authenticated-only Results fast path: source isolation and settlement parity."""
from copy import deepcopy

from tbt.services import entitlements as access
from tbt.services import match_status as runtime


def _result(event_id="historical-1"):
    return {
        "event_id": event_id,
        "scheduled_at": "2026-11-10T11:00:00+00:00",
        "player1": {"id": "11", "name": "Alpha", "model": {"confidence": 0.72}},
        "player2": {"id": "22", "name": "Beta"},
        "market_publications": [
            {
                "section": "top_daily", "market": "match_winner",
                "selection_id": "11", "issued_at": "2026-11-10T06:00:00+00:00",
                "result": {"correct": True, "profit_units": 0.7},
            },
            {
                "section": "internal_private", "market": "internal_model",
                "selection_id": "secret", "result": {"correct": False},
            },
        ],
    }


def _authorized_feed():
    raw = _result()
    detached = access._filter_result_history(
        [raw], None, allowed_categories={"top_daily"}
    )
    assert len(detached) == 1
    assert len(detached[0]["market_publications"]) == 1
    assert detached[0] is not raw
    return raw, {"results": detached}


def test_default_runtime_helper_still_deepcopies_existing_result_rows(monkeypatch):
    raw, authorized = _authorized_feed()
    baseline = deepcopy(raw)
    copies = []
    original = runtime.deepcopy

    def observed(value):
        copies.append(value)
        return original(value)

    monkeypatch.setattr(runtime, "deepcopy", observed)
    ordinary = runtime.runtime_settled_results(authorized, {})
    assert len(copies) == 1
    assert ordinary == authorized["results"]
    assert ordinary[0] is not authorized["results"][0]

    copies.clear()
    borrowed = runtime.runtime_settled_results(
        authorized, {}, already_detached=True
    )
    assert copies == [], "No second full historical Results deepcopy"
    assert borrowed == ordinary
    assert borrowed is not authorized["results"]
    assert borrowed[0] is authorized["results"][0]

    final = access.filter_results_for_categories(borrowed, {"top_daily"})
    assert final == ordinary
    assert final[0] is not borrowed[0]
    assert final[0]["market_publications"][0] is not borrowed[0]["market_publications"][0]
    final[0]["player1"]["model"]["confidence"] = 0.01
    final[0]["market_publications"][0]["result"]["correct"] = False
    assert authorized["results"][0]["player1"]["model"]["confidence"] == 0.72
    assert raw == baseline
    assert "secret" not in str(final)


def test_runtime_settlement_same_rows_and_finance_before_and_after_fast_path():
    raw, authorized = _authorized_feed()
    baseline = deepcopy(raw)
    row = {
        "event_id": "new-101",
        "scheduled_at": "2026-11-12T12:00:00+00:00",
        "winner_id": "11",
        "player1": {"id": "11", "name": "Alpha"},
        "player2": {"id": "22", "name": "Beta"},
        "betting": {"selection_id": "11", "odds": 1.62},
        "market_publications": [{
            "issued_at": "2026-11-12T06:00:00+00:00",
            "publication_status": "published", "section": "top_daily",
            "market": "match_winner", "selection_id": "11",
            "odds": 1.62, "result": None,
        }],
    }
    issued_copy = deepcopy(row)
    authorized["top_daily_picks"] = [row]
    statuses = {"new-101": {
        "status": "win", "checked_at": "2026-11-12T14:00:00+00:00",
    }}
    ordinary = runtime.runtime_settled_results(authorized, statuses)
    borrowed = runtime.runtime_settled_results(
        authorized, statuses, already_detached=True
    )
    assert ordinary == borrowed
    assert len(ordinary) == len(borrowed) == 2
    assert all(len(item["market_publications"]) == 1 for item in borrowed)
    assert borrowed[0]["market_publications"][0]["result"]["correct"] is True
    assert abs(borrowed[0]["market_publications"][0]["result"]["profit_units"] - 0.62) < 1e-12

    normal_final = access.filter_results_for_categories(ordinary, {"top_daily"})
    fast_final = access.filter_results_for_categories(borrowed, {"top_daily"})
    assert fast_final == normal_final
    fast_final[-1]["player1"]["model"]["confidence"] = 0.1
    assert authorized["results"][0]["player1"]["model"]["confidence"] == 0.72
    assert raw == baseline
    assert row == issued_copy


def test_fast_path_requires_explicit_opt_in_and_does_not_edit_input_list():
    _raw, authorized = _authorized_feed()
    before = list(authorized["results"])
    result = runtime.runtime_settled_results(
        authorized, {}, already_detached=True
    )
    result.reverse()
    assert authorized["results"] == before
    assert result[0] is authorized["results"][0]
