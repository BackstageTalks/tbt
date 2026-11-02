"""2 Nov 2026: a premature winnerCode must never generate a green result."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tbt.services.match_status import (
    _NOV2_ISSUED_WINNER_IDS,
    classify_finished_event,
    filter_unverified_nov2_winner_results,
    runtime_settled_results,
    scan_match_statuses,
    verified_terminal_statuses,
)


NOW = datetime(2026, 11, 2, 21, 0, tzinfo=timezone.utc)


def row(event="17467283", selected="p2", day="2026-11-02T11:30:00Z"):
    return {
        "event_id": event, "scheduled_at": day, "winner_id": selected,
        "player1": {"id": "p1", "name": "First"},
        "player2": {"id": "p2", "name": "Second"},
        "betting": {"selection_id": selected, "odds": 1.54},
        "issued_at": "2026-11-02T05:37:35Z",
    }


def event(event_id="17467283", winner=2, with_scores=True):
    item = {
        "id": event_id, "status": {"type": "finished", "description": "Ended"},
        "winnerCode": winner, "homeTeam": {"id": "p1"},
        "awayTeam": {"id": "p2"},
    }
    if with_scores:
        item["homeScore"] = {"period1": 2, "period2": 4}
        item["awayScore"] = {"period1": 6, "period2": 6}
    return item


def archived(correct=True):
    source = row()
    source["market_publications"] = [{
        "section": "top_daily", "market": "match_winner",
        "selection_id": "p2", "odds": 1.54, "issued_at": source["issued_at"],
        "result": {"status": "hit" if correct else "miss", "correct": correct,
                   "profit_units": 0.54 if correct else -1.0},
    }]
    return source


def test_frozen_morning_winner_ids_not_other_markets():
    snapshot = json.loads((Path(__file__).resolve().parents[1]
                           / "api/data/confirmed_daily_offer_20261102.json").read_text())
    winners = {p["event_id"] for p in snapshot["issued_picks"]
               if p["market"] == "match_winner"}
    assert winners == _NOV2_ISSUED_WINNER_IDS
    assert len(winners) == 4


def test_finished_winner_code_without_completed_sets_is_ungraded():
    source = row()
    assert classify_finished_event(source, event(with_scores=False), checked_at=NOW) is None
    partial = event()
    partial["homeScore"]["period2"] = 2
    partial["awayScore"]["period2"] = 3
    assert classify_finished_event(source, partial, checked_at=NOW) is None


def test_score_winner_disagreement_does_not_settle():
    contradicting = event(winner=1)
    assert classify_finished_event(row(), contradicting, checked_at=NOW) is None


def test_verified_final_set_score_generates_only_correct_pnl():
    source = row()
    verified = classify_finished_event(source, event(), checked_at=NOW)
    assert verified["status"] == "win"
    assert verified["winner_id"] == "p2"
    assert verified["provider_final_score_verified"] is True
    assert verified_terminal_statuses({source["event_id"]: verified})
    response = runtime_settled_results({"top_daily_picks": [source], "results": []},
                                       {source["event_id"]: verified})
    assert len(response) == 1
    settled = response[0]["market_publications"][0]["result"]
    assert settled["correct"] is True
    assert abs(settled["profit_units"] - 0.54) < 1e-8


def test_wrong_archive_win_quarantined_until_verified_readback():
    source = archived()
    stale = {"status": "win", "winner_id": "p2", "provider_status": "finished",
             "checked_at": NOW.isoformat()}
    assert filter_unverified_nov2_winner_results([source], {source["event_id"]: stale}) == []
    assert filter_unverified_nov2_winner_results([source], {}) == []
    final_loss = classify_finished_event(row(selected="p1"), event(), checked_at=NOW)
    assert final_loss["status"] == "loss"
    assert filter_unverified_nov2_winner_results([source], {source["event_id"]: final_loss}) == []
    recalculated = runtime_settled_results(
        {"top_daily_picks": [row(selected="p1")], "results": []},
        {source["event_id"]: final_loss},
    )
    assert recalculated[0]["market_publications"][0]["result"]["profit_units"] == -1


def test_confirmed_archive_win_remains_after_same_winner_readback():
    source = archived()
    confirmed = classify_finished_event(row(), event(), checked_at=NOW)
    assert filter_unverified_nov2_winner_results(
        [source], {source["event_id"]: confirmed}
    ) == [source]


def test_unverified_previous_terminal_is_rechecked_by_original_worker():
    source = row()
    old = {"statuses": {source["event_id"]: {
        "status": "win", "provider_status": "finished", "winner_id": "p2",
        "checked_at": (NOW-timedelta(hours=1)).isoformat(),
    }}}

    class Provider:
        def live_events(self):
            return [event(winner=2, with_scores=False)]
        def previous_player_matches(self, player_id, page=0):
            return {"events": []}

    scanned = scan_match_statuses(
        {"top_daily_picks": [source]}, Provider(), old,
        now=NOW, max_checks=1, max_near_checks=0,
    )
    assert source["event_id"] not in scanned["statuses"]
    assert scanned["pending_count"] == 1


def test_historical_winners_are_never_changed():
    old = row("historic-199", day="2026-10-20T11:00:00Z")
    old["market_publications"] = archived()["market_publications"]
    assert filter_unverified_nov2_winner_results([old], {}) == [old]
    unscored = event("historic-199", with_scores=False)
    assert classify_finished_event(old, unscored, checked_at=NOW)["status"] == "win"
    assert verified_terminal_statuses({"historic-199": {"status": "win"}})


def test_void_and_retirement_not_turned_into_wins():
    source = archived()
    source["market_publications"][0]["result"] = {
        "status": "retired", "correct": None, "void": True, "profit_units": 0,
    }
    status = {"status": "retired", "provider_status": "finished retired"}
    assert filter_unverified_nov2_winner_results(
        [source], {source["event_id"]: status}
    ) == [source]
