"""Approved frozen local Aces prices count exactly once across historical Results."""
from copy import deepcopy
from datetime import datetime, timezone

from tbt.services.local_ace_results import local_ace_result_odds
from tbt.services.dashboard_kpis import published_results_metrics
from tbt.services.engine import betting_performance


def _row(event, selection, correct, *, day="2026-11-02", odds=None,
         price_status="projection_only", basis=None, line=4.5, contract="player_total_ou"):
    pub = {
        "market": "aces", "section": "ace", "selection_id": selection,
        "price_contract": contract, "ou_side": "over", "market_line": line,
        "price_status": price_status, "odds": odds, "price_basis": basis,
        "issued_at": f"{day}T07:30:00Z", "publication_status": "published",
        "result": {"correct": correct, "status": "hit" if correct else "miss"},
    }
    return {"event_id": event, "scheduled_at": f"{day}T14:00:00Z",
            "market_publications": [pub]}


def test_local_aces_win_loss_count_as_normal_1u_stakes_in_every_window():
    won = _row("17467964", "270414", True, odds=1.79,
               price_status="priced_projection", basis="local_aces_statistical_v1")
    lost = _row("17468525", "289146", False)
    original = deepcopy([won, lost])
    expected_price = local_ace_result_odds(lost, lost["market_publications"][0])
    assert expected_price is not None and 1.60 <= expected_price <= 1.80
    rows = [won, lost]
    backend = published_results_metrics({"results": rows}, "7",
                now=datetime(2026, 11, 5, tzinfo=timezone.utc))
    engine = betting_performance(rows)["overall"]
    for result in (backend, engine):
        assert result["wins"] == 1 and result["losses"] == 1
        assert result["staked_units"] == 2
        assert abs(result["profit_units"] - (-0.21)) < 1e-9
        assert abs(result["roi"] + .105) < 1e-9
    assert rows == original


def test_local_aces_refuse_old_or_ambiguous_contracts_without_changing_history():
    prior = _row("legacy", "person", True, day="2026-10-31")
    no_line = _row("new", "person", True, line=None)
    wrong = _row("new", "person", True, contract="player_superiority")
    late = _row("new", "person", True)
    late["market_publications"][0]["issued_at"] = "2026-11-02T15:30:00Z"
    for row in (prior, no_line, wrong, late):
        pub = row["market_publications"][0]
        assert local_ace_result_odds(row, pub) is None
        assert betting_performance([row])["overall"]["staked_units"] == 0


def test_approved_local_and_winner_are_both_in_same_overall_roi():
    local = _row("a", "a-pick", True, odds=1.73,
                 price_status="priced_projection", basis="local_aces_statistical_v1")
    winner = {"event_id": "b", "scheduled_at": "2026-11-02T14:00:00Z",
              "market_publications": [{
                  "market": "match_winner", "section": "top_daily",
                  "selection_id": "b-pick", "issued_at": "2026-11-02T07:30:00Z",
                  "price_status": "priced", "odds": 1.98,
                  "result": {"correct": True, "staked_units": 1.0, "profit_units": .98},
              }]}
    rows = [local, winner]
    overall = betting_performance(rows)["overall"]
    assert overall["n"] == 2 and overall["staked_units"] == 2
    assert abs(overall["profit_units"] - 1.71) < 1e-9
    dashboard = published_results_metrics({"results": rows}, "7",
               now=datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert dashboard["stake_count"] == 2
    assert abs(dashboard["roi"] - .855) < 1e-9


def test_separate_frozen_ou_lines_count_once_each_but_duplicate_receipt_dedupes():
    first = _row("same", "player", True, odds=1.72,
                 price_status="priced_projection", basis="local_aces_statistical_v1", line=4.5)
    second = deepcopy(first)
    second["market_publications"][0]["market_line"] = 5.5
    duplicate = deepcopy(first)
    for source in (betting_performance,):
        metrics = source([first, second, duplicate])["overall"]
        assert metrics["n"] == 2
        assert metrics["staked_units"] == 2.0
        assert abs(metrics["profit_units"] - 1.44) < 1e-9
    backend = published_results_metrics({"results": [first, second, duplicate]}, "7",
              now=datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert backend["sample"] == 2 and backend["stake_count"] == 2
