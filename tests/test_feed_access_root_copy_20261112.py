"""The feed root copy must be cheap without weakening entitlement isolation."""
from copy import deepcopy

import pytest

import tbt.services.entitlements as entitlements


def _source_feed():
    pick = {
        "event_id": "tip-1",
        "scheduled_at": "2026-11-12T12:00:00+00:00",
        "market": "match_winner",
        "selection_id": "p1",
        "player1": {"id": "p1", "name": "Original"},
        "player2": {"id": "p2", "name": "Opponent"},
        "betting": {"selection_id": "p1"},
    }
    return {
        "upcoming": [deepcopy(pick)],
        "top_daily_picks": [],
        "prime_picks": [],
        "value_picks": [pick],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
        "results": [{
            "event_id": "historic-1",
            "scheduled_at": "2026-11-10T12:00:00+00:00",
            "player1": {"id": "p1", "name": "Original"},
            "player2": {"id": "p2", "name": "Opponent"},
            "market_publications": [{
                "section": "top_daily", "market": "match_winner",
                "selection_id": "p1",
                "issued_at": "2026-11-10T09:00:00+00:00",
                "result": {"correct": True, "status": "settled"},
            }],
        }],
        "performance_windows": {"all": {"model": {"n": 1, "accuracy": 1.0}}},
        "market_selection": {"top_daily_rule": {}},
    }


def _ui():
    plans = ("rookie", "pro", "elite", "legend", "goat")
    return {
        "elements": {"SIDEBAR_RESULTS": {
            "access": {plan: "active" for plan in plans},
        }},
        "dashboard": {
            "results_history_window": {plan: "all" for plan in plans},
            "daily_hub": {"tabs": {}},
        },
    }


@pytest.mark.parametrize("plan", ["rookie", "pro", "elite", "legend", "goat", "admin"])
def test_feed_filter_skips_full_root_deepcopy_and_keeps_source_unchanged(monkeypatch, plan):
    source = _source_feed()
    original = deepcopy(source)
    original_copy = entitlements.deepcopy

    def reject_root_copy(value, *args, **kwargs):
        assert value is not source, "access filter must not deep-copy full source"
        return original_copy(value, *args, **kwargs)

    monkeypatch.setattr(entitlements, "deepcopy", reject_root_copy)
    account = {"plan": plan, "status": "active", "id": "member-1"}
    if plan == "admin":
        account["role"] = "admin"
    served, manifest = entitlements.filter_feed_for_access(source, account, _ui())

    assert source == original, "filter must not mutate canonical source"
    assert served is not source
    assert served["results"] is not source["results"]
    assert manifest["plan"] == plan


@pytest.mark.parametrize("plan", ["elite", "legend", "goat", "admin"])
def test_full_access_upcoming_offers_and_results_are_independent_of_source(plan):
    source = _source_feed()
    original = deepcopy(source)
    account = {"plan": plan, "status": "active", "id": "member-1"}
    if plan == "admin":
        account["role"] = "admin"
    served, _ = entitlements.filter_feed_for_access(source, account, _ui())

    assert len(served["upcoming"]) == 1
    assert len(served["value_picks"]) == 1
    assert len(served["results"]) == 1
    served["upcoming"][0]["player1"]["name"] = "changed"
    served["value_picks"][0]["betting"]["selection_id"] = "changed"
    served["results"][0]["market_publications"][0]["result"]["correct"] = False
    assert source == original, "response processing must never mutate issued source"


def test_locked_member_does_not_receive_unfiltered_upcoming_or_result_details():
    source = _source_feed()
    original = deepcopy(source)
    data, manifest = entitlements.filter_feed_for_access(
        source, {"plan": "rookie", "status": "active", "id": "free-1"}, _ui()
    )
    assert manifest["plan"] == "rookie"
    assert data["upcoming"] is not source["upcoming"]
    for row in data["upcoming"]:
        assert "betting" not in row
        assert "winner_id" not in row
    assert source == original
