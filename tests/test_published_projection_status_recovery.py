"""Regression checks for same-day settled published, priced projection-only cards."""
from copy import deepcopy
from datetime import datetime, timezone

from tbt.services.match_status import (
    classify_finished_event,
    deployed_priced_projection,
    prediction_rows,
    runtime_settled_results,
    scan_match_statuses,
)
from tbt.services.results_archive import settled_archive_candidates


NOW = datetime(2026, 10, 12, 13, 0, tzinfo=timezone.utc)
ISSUED = "2026-10-12T04:12:00+00:00"
CAPTURED = "2026-10-12T04:05:00+00:00"
START = "2026-10-12T08:00:00+00:00"


def _row(market="games", selection="Under 20.5 Games", **updates):
    row = {
        "event_id": "17304964",
        "scheduled_at": START,
        "winner_id": "11",
        "player1": {"id": "11", "name": "Alpha"},
        "player2": {"id": "22", "name": "Beta"},
        "market": market,
        "selection": selection,
        "price_status": "priced_projection",
        "odds": 1.60,
        "provider_id": 1,
        "captured_at": CAPTURED,
        "best_of": 3,
    }
    row.update(updates)
    return row


def _feed(row):
    return {"generated_at": ISSUED, "top_daily_picks": [], "prime_picks": [],
            "sg_picks": [row] if row.get("market") in {"games", "sets"} else [],
            "ace_picks": [row] if row.get("market") in {"aces", "double_faults"} else [],
            "results": []}


def _final_event(**updates):
    row = {
        "id": "17304964",
        "homeTeam": {"id": "11"}, "awayTeam": {"id": "22"},
        "winnerCode": 1,
        "status": {"type": "finished", "description": "Ended"},
        "homeScore": {"period1": 6, "period2": 6},
        "awayScore": {"period1": 3, "period2": 3},
    }
    row.update(updates)
    return row


class _Provider:
    def live_events(self):
        return []

    def previous_player_matches(self, player_id, page=0):
        return {"events": [_final_event()]}


def test_issued_priced_stat_only_fixture_is_not_invisible_to_worker():
    feed = _feed(_row())
    assert set(prediction_rows(feed, now=NOW)) == {"17304964"}
    snapshot = scan_match_statuses(feed, _Provider(), now=NOW)
    assert snapshot["newly_resolved"] == 1
    assert snapshot["statuses"]["17304964"]["projection_stats"] == {
        "total_sets": 2, "total_games": 18,
    }
    rows = runtime_settled_results(feed, snapshot["statuses"])
    assert len(rows) == 1
    publication = rows[0]["market_publications"][0]
    assert publication["market"] == "games"
    assert publication["reference_projection"] == 20.5
    assert publication["result"]["correct"] is True
    assert abs(publication["result"]["profit_units"] - 0.60) < 1e-9
    durable = settled_archive_candidates(feed, snapshot["statuses"])
    assert len(durable) == 1
    assert durable[0]["market_publications"][0]["result"]["status"] == "hit"


def test_multiple_stat_only_bet_types_have_real_frozen_market_terms():
    for market, selection, extra, expected in (
        ("sets", "Under 2.5 Sets", {}, "sets:under:2.5"),
        ("aces", "Under 6.5 Aces", {"projection_subject_id": "11"}, "11"),
        ("double_faults", "Over 3.5 Double Faults",
         {"projection_subject_id": "22"}, "22"),
    ):
        row = _row(market, selection, **extra)
        offer = deployed_priced_projection(row, _feed(row))
        assert offer is not None, (market, offer)
        assert offer["market"] == market
        assert offer["selection_id"] == expected
        assert offer["odds"] == 1.60
        assert offer["price_status"] == "priced_projection"


def test_unpriced_late_or_unverified_quote_never_enters_worker():
    cases = [
        {"price_status": "projection_only"},
        {"captured_at": "2026-10-12T09:00:00+00:00"},
        {"odds": None},
        {"provider_id": None},
        {"excluded_reason": "not_qualified"},
        {"selection": "Under 20.5 Games", "line": 19.5},
    ]
    for changes in cases:
        row = _row(**changes)
        feed = _feed(row)
        assert deployed_priced_projection(row, feed) is None, changes
        assert prediction_rows(feed, now=NOW) == {}, changes
        assert runtime_settled_results(
            feed, {"17304964": {"status": "win", "provider_home_id": "11",
                                 "provider_away_id": "22", "projection_stats": {
                                     "total_sets": 2, "total_games": 18}}}
        ) == [], changes

    valid = _feed(_row())
    valid["generated_at"] = "2026-10-12T09:30:00+00:00"
    assert prediction_rows(valid, now=NOW) == {}


def test_direct_winner_id_is_valid_only_with_matching_identity_and_terminal_status():
    row = _row()
    event = _final_event()
    event.pop("winnerCode")
    event["winnerId"] = "11"
    assert classify_finished_event(row, event)["status"] == "win"
    wrong = deepcopy(event)
    wrong["winnerId"] = "999"
    assert classify_finished_event(row, wrong) is None
    conflicting = deepcopy(event)
    conflicting["winnerCode"] = 2
    assert classify_finished_event(row, conflicting) is None
    active = deepcopy(event)
    active["status"] = {"type": "inprogress", "description": "2nd set"}
    assert classify_finished_event(row, active) is None
