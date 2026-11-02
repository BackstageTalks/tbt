"""Regression: existing verified terminal settlement must reach 2 Nov Results.

Only published, settled picks may appear in Results; a new storage-only flag
must never be required to display a provider-confirmed terminal match winner.
"""
from datetime import datetime, timezone

from tbt.services.match_status import (
    classify_finished_event,
    runtime_settled_results,
    scan_match_statuses,
    verified_terminal_statuses,
)

NOW = datetime(2026, 11, 2, 21, 0, tzinfo=timezone.utc)


def row(event_id="17467283", selected="p2"):
    return {
        "event_id": event_id,
        "scheduled_at": "2026-11-02T11:30:00Z",
        "winner_id": selected,
        "player1": {"id": "p1", "name": "First"},
        "player2": {"id": "p2", "name": "Second"},
        "betting": {"selection_id": selected, "odds": 1.54},
        "issued_at": "2026-11-02T05:37:35Z",
    }


def event(winner=2, status="finished", with_scores=False):
    value = {
        "id": "17467283",
        "status": {"type": status, "description": "Ended"},
        "winnerCode": winner,
        "homeTeam": {"id": "p1"},
        "awayTeam": {"id": "p2"},
    }
    if with_scores:
        value["homeScore"] = {"period1": 2, "period2": 4}
        value["awayScore"] = {"period1": 6, "period2": 6}
    return value


def test_finished_winner_is_settled_without_new_score_flag():
    outcome = classify_finished_event(row(), event(), checked_at=NOW)
    assert outcome is not None and outcome["status"] == "win"
    assert outcome["winner_id"] == "p2"
    assert "provider_final_score_verified" not in outcome
    assert verified_terminal_statuses({"17467283": outcome})["17467283"] == outcome


def test_previous_terminal_snapshot_without_flag_is_retained_by_worker():
    published = row()
    old = {
        "status": "win", "provider_status": "finished ended",
        "winner_id": "p2", "provider_home_id": "p1", "provider_away_id": "p2",
        "checked_at": "2026-11-02T20:00:00Z",
    }

    class Provider:
        def live_events(self):
            raise AssertionError("Settled events must not be re-queried")
        def previous_player_matches(self, player_id, page=0):
            raise AssertionError("Settled events must not be re-queried")

    state = scan_match_statuses(
        {"top_daily_picks": [published]}, Provider(),
        {"statuses": {"17467283": old}}, now=NOW,
        max_checks=1, max_near_checks=0,
    )
    assert state["statuses"]["17467283"]["status"] == "win"


def test_snapshot_winner_reaches_published_top_result_and_pnl():
    source = row()
    status = {"status": "win", "winner_id": "p2",
              "provider_status": "finished ended", "checked_at": NOW.isoformat()}
    values = runtime_settled_results(
        {"top_daily_picks": [source], "results": []}, {"17467283": status},
    )
    assert len(values) == 1
    result = values[0]["market_publications"][0]["result"]
    assert result["correct"] is True
    assert abs(result["profit_units"] - 0.54) < 1e-8


def test_snapshot_loss_reaches_published_top_result():
    source = row("17471474", "p1")
    source["betting"]["odds"] = 1.51
    status = {"status": "loss", "winner_id": "p2",
              "provider_status": "finished ended", "checked_at": NOW.isoformat()}
    values = runtime_settled_results(
        {"top_daily_picks": [source], "results": []}, {"17471474": status},
    )
    assert len(values) == 1
    result = values[0]["market_publications"][0]["result"]
    assert result["correct"] is False
    assert result["profit_units"] == -1


def test_live_winner_code_still_cannot_settle():
    assert classify_finished_event(
        row(), event(status="inprogress", with_scores=False), checked_at=NOW
    ) is None
    assert verified_terminal_statuses({
        "17467283": {"status": "win", "provider_status": "inprogress 2nd set"}
    }) == {}
