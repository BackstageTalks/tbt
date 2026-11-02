"""2 November 2026 Results must match the exact delivered morning contracts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tbt.services.entitlements import filter_results_for_issued_day


SNAPSHOT = json.loads(
    (Path(__file__).resolve().parents[1] / "api/data/confirmed_daily_offer_20261102.json")
    .read_text(encoding="utf-8")
)
OFFERS = SNAPSHOT["issued_picks"]


def _manifest(plan: str, *, top="ALL", value="ALL", ace="ALL"):
    categories = {"top_daily", "value", "ace", "prime"}
    return {
        "plan": plan,
        "result_categories": list(categories),
        "sections": {
            key: {
                "enabled": True,
                "display_state": "active",
                "visible_picks": limit,
                "row_overrides": {},
            }
            for key, limit in (
                ("daily", top), ("value", value), ("ace", ace), ("prime", "ALL")
            )
        },
    }


def _result(offer: dict) -> dict:
    pub = {
        "section": offer["section"],
        "market": offer["market"],
        "selection_id": offer["selection_id"],
        "publication_key": offer["publication_key"],
        "result": {"correct": True, "profit_units": 0.5},
    }
    if offer["market"] == "aces":
        pub.update({
            "price_contract": "player_total_ou",
            "ou_side": offer["ou_side"],
            "market_line": offer["market_line"],
        })
    return {
        "event_id": offer["event_id"],
        "scheduled_at": offer["scheduled_at"],
        "market_publications": [pub],
    }


def _identity(rows):
    return {
        (r["event_id"], p["section"], p["market"], p["selection_id"])
        for r in rows for p in r["market_publications"]
    }


def _all_offered_results():
    return [_result(offer) for offer in OFFERS]


def test_snapshot_is_exact_sent_morning_and_reissued_offer():
    assert SNAPSHOT["betting_day"] == "2026-11-02"
    assert SNAPSHOT["provenance"]["morning_message_ids"] == [725, 726]
    assert SNAPSHOT["provenance"]["aces_message_ids"] == [727, 728]
    assert len(OFFERS) == 9
    assert sum(o["section"] == "top_daily" for o in OFFERS) == 3
    assert sum(o["section"] == "value" for o in OFFERS) == 1
    assert sum(o["market"] == "aces" for o in OFFERS) == 5
    assert [o["event_id"] for o in OFFERS if o["free"]] == ["17467283"]
    assert [(o["selection_id"], o["market_line"]) for o in OFFERS if o["market"] == "aces"] == [
        ("289146", 12.5), ("158896", 10.5), ("372310", 6.5),
        ("270414", 4.5), ("341853", 7.5)
    ]


def test_elite_only_nine_issued_contracts_not_unissued_prime_or_opponent():
    rows = _all_offered_results()
    rows.extend([
        {
            "event_id": "not-issued", "scheduled_at": "2026-11-02T12:00:00+00:00",
            "market_publications": [{"section": "prime", "market": "match_winner",
                                     "selection_id": "unknown", "result": {"correct": True}}],
        },
        {
            "event_id": "17449526", "scheduled_at": "2026-11-02T10:00:00+00:00",
            "market_publications": [{"section": "ace", "market": "aces",
                                     "selection_id": "the-opponent",
                                     "price_contract": "player_total_ou",
                                     "ou_side": "over", "market_line": 10.5,
                                     "result": {"correct": True}}],
        },
    ])
    retained = filter_results_for_issued_day(rows, _manifest("elite"))
    assert _identity(retained) == _identity(_all_offered_results())
    assert len(retained) == 9


@pytest.mark.parametrize("plan,expected", [
    ("pro", 4), ("rookie", 1), ("elite", 9),
    ("legend", 10), ("goat", 10), ("admin", 10),
])
def test_tiers_scope_only_current_snapshot_and_full_tiers_unrestricted(plan, expected):
    rows = _all_offered_results()
    rows.append({
        "event_id": "other-prime", "scheduled_at": "2026-11-02T10:00:00+00:00",
        "market_publications": [{"section": "prime", "market": "match_winner",
                                 "selection_id": "3", "result": {"correct": True}}],
    })
    before = json.dumps(rows, sort_keys=True)
    got = filter_results_for_issued_day(rows, _manifest(plan, top=3))
    assert len(got) == expected
    assert json.dumps(rows, sort_keys=True) == before
    if plan == "rookie":
        assert {(r["event_id"], p["selection_id"]) for r in got
                for p in r["market_publications"]} == {("17467283", "52229")}
    if plan == "pro":
        assert {p["market"] for r in got for p in r["market_publications"]} == {"match_winner"}


def test_ace_result_never_changes_contract_or_reintroduces_superiority():
    original = _result(next(o for o in OFFERS if o["event_id"] == "17449526"))
    good = filter_results_for_issued_day([original], _manifest("elite"))
    assert len(good) == 1
    for key, fake in (
        ("market_line", 9.5), ("ou_side", "under"),
        ("publication_key", "ace:projection:aces:player:17449526:158896"),
        ("price_contract", "player_superiority"),
    ):
        row = json.loads(json.dumps(original))
        row["market_publications"][0][key] = fake
        assert filter_results_for_issued_day([row], _manifest("elite")) == []


def test_hidden_category_and_top_position_limit_stay_authoritative():
    rows = _all_offered_results()
    pro = filter_results_for_issued_day(rows, _manifest("pro", top=1))
    assert {r["event_id"] for r in pro} == {"17456690", "17470634"}
    restricted = _manifest("elite")
    restricted["sections"]["ace"]["display_state"] = "hidden"
    restricted["result_categories"].remove("ace")
    assert len(filter_results_for_issued_day(rows, restricted)) == 4
    restricted = _manifest("rookie")
    restricted["sections"]["daily"]["display_state"] = "hidden"
    assert filter_results_for_issued_day(rows, restricted) == []


def test_historical_result_is_never_regraded_or_deleted():
    old = {
        "event_id": "historical", "scheduled_at": "2026-10-31T11:00:00+00:00",
        "market_publications": [{"section": "ace", "market": "aces",
                                 "selection_id": "legacy", "result": {"correct": False}}],
    }
    for plan in ("rookie", "pro", "elite", "legend", "goat"):
        assert filter_results_for_issued_day([old], _manifest(plan)) == [old]


def test_runtime_second_pass_is_present_after_category_gate():
    app = (Path(__file__).resolve().parents[1] / "api/function_app.py").read_text(encoding="utf-8")
    assert 'data["results"] = filter_results_for_categories(' in app
    assert 'data["results"] = filter_results_for_issued_day(' in app
