"""Synthetic parity contracts. No private tennis rows in public CI."""
from copy import deepcopy
import pytest
from audit_711_721_pick_parity import compare

START = "2026-10-19T11:00:00Z"
TAKEN = "2026-10-18T09:00:00Z"


def snap(event="e1", selected="a", section="top_daily", odds=1.7):
    return {
        "schema": 1, "generated_at": TAKEN,
        "scope": {"post_match_fields_excluded": True},
        "rows": [{
            "event_id": event, "scheduled_at": START, "tour": "ATP",
            "player1": {"id": "a"}, "player2": {"id": "b"},
            "selected_section": section,
            "betting": {
                "selection_id": selected, "odds": odds,
                "betting_day": "2026-10-19",
            },
        }],
    }


def ledger(event="e1", selection="a", correct=True, status="settled"):
    return [{
        "event_id": event, "tour": "ATP",
        "player1": {"id": "a"}, "player2": {"id": "b"},
        "market_publications": [{
            "market": "match_winner", "selection_id": selection,
            "result": {"status": status, "correct": correct},
        }],
    }]


def test_same_pick_never_changes_result_even_if_probability_category_or_odds_change():
    a = snap()
    b = snap(section="value", odds=1.82)
    b["rows"][0]["player1"]["probability"] = 0.89
    report = compare(a, b, ledger())
    assert report["shared_exact_picks"] == report["shared_settled_or_void_verified"] == 1
    assert report["shared_outcome_disagreements"] == 0
    assert report["shared_7_1_1"]["wins"] == report["shared_7_2_1"]["wins"] == 1
    assert report["shared_7_1_1"]["hit_rate"] == report["shared_7_2_1"]["hit_rate"] == 1
    assert report["same_pick_moved_top_value"] == 1
    assert report["shared_picks_with_changed_price"] == 1
    assert report["shared_7_1_1"]["roi"] != report["shared_7_2_1"]["roi"]


def test_opposite_player_is_different_pick_and_opposite_grade():
    report = compare(snap(), snap(selected="b"), ledger())
    assert report["shared_exact_picks"] == 0
    assert report["same_fixture_different_selected_side"] == 1
    assert report["only_7_1_1"]["wins"] == 1
    assert report["only_7_2_1"]["losses"] == 1


def test_different_event_is_unshared_even_if_same_player_id():
    report = compare(snap(), snap(event="e2"), ledger())
    assert report["shared_exact_picks"] == 0
    assert report["only_7_2_1"]["pending_or_unverified"] == 1


def test_unsettled_is_not_defeat():
    report = compare(snap(), snap(), ledger(status="pending", correct=None))
    assert report["shared_settled_or_void_verified"] == 0
    assert report["shared_7_1_1"]["settled"] == 0
    assert report["shared_7_1_1"]["hit_rate"] is None


def test_void_not_counted_as_win_or_loss():
    report = compare(snap(), snap(), ledger(status="void", correct=False))
    assert report["shared_settled_or_void_verified"] == 1
    assert report["shared_7_1_1"]["void"] == 1
    assert report["shared_7_1_1"]["settled"] == 0


def test_inconsistent_canonical_settlement_fails_closed():
    data = ledger()
    data[0]["market_publications"].append({
        "market": "match_winner", "selection_id": "a",
        "result": {"correct": False},
    })
    with pytest.raises(ValueError, match="Contradictory"):
        compare(snap(), snap(), data)


def test_identity_swap_fails_closed():
    other = snap()
    other["rows"][0]["player2"]["id"] = "other"
    with pytest.raises(ValueError, match="fixture identity"):
        compare(snap(), other, ledger())


def test_hindsight_snapshot_fails_closed():
    other = snap()
    other["generated_at"] = "2026-10-19T12:00:00Z"
    with pytest.raises(ValueError, match="after match start"):
        compare(snap(), other, ledger())


def test_post_match_payload_fails_closed():
    other = snap()
    other["rows"][0]["result"] = {"correct": True}
    with pytest.raises(ValueError, match="leaked"):
        compare(snap(), other, ledger())


def test_low_price_fails_closed():
    with pytest.raises(ValueError, match="1.50"):
        compare(snap(odds=1.49), snap(), ledger())


def test_duplicate_key_fails_closed():
    other = snap()
    other["rows"].append(deepcopy(other["rows"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        compare(snap(), other, ledger())


def test_missing_outcome_is_not_fabricated():
    report = compare(snap(), snap(), [])
    assert report["shared_exact_picks"] == 1
    assert report["shared_settled_or_void_verified"] == 0
    assert report["shared_7_1_1"]["pending_or_unverified"] == 1
