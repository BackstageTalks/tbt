"""Immutable serving receipts survive the Bratislava 06:00 Results rollover."""
from copy import deepcopy
from datetime import datetime, timezone

from tbt.services.issued_authority import row_authority_key
from tbt.services.match_status import (
    confirmed_rollover_rows, feed_with_issued_rollover, scan_match_statuses,
)
from tbt.services.results_archive import settled_archive_candidates


DAY6 = datetime(2026, 11, 6, 15, tzinfo=timezone.utc)
DAY7 = datetime(2026, 11, 7, 7, tzinfo=timezone.utc)
ISSUED = "2026-11-06T05:20:00+00:00"
STARTED = "2026-11-06T12:00:00+00:00"


def _ace():
    return {
        "event_id": "ace-match-123",
        "scheduled_at": STARTED,
        "player1": {"id": "p1", "name": "Alpha"},
        "player2": {"id": "p2", "name": "Beta"},
        "winner_id": "p1",
        "selection_id": "p1",
        "market": "aces",
        "projection": 7.8,
        "market_publications": [{
            "section": "ace", "market": "aces", "selection_id": "p1",
            "publication_key": "local-aces-ou-v1:ace-match-123:p1:over:5.5",
            "publication_status": "published",
            "price_contract": "player_total_ou", "ou_side": "over",
            "market_line": 5.5, "projection": 7.8,
            "projection_scope": "player", "projection_metric": "aces",
            "issued_at": ISSUED, "odds": 1.70,
            "price_status": "priced_projection",
            "price_basis": "local_aces_statistical_v1",
            "source": "confirmed_telegram_ou_reissue",
        }],
    }


def _day6(row):
    return {
        "schema": 1,
        "generated_at": ISSUED,
        "ace_picks": [row],
        "top_daily_picks": [],
        "results": [],
    }


def _day7():
    return {
        "schema": 1,
        "generated_at": "2026-11-07T05:25:00+00:00",
        "ace_picks": [], "top_daily_picks": [], "results": [],
    }


def _receipt(row):
    return {"schema": 1, "confirmed_only": True, "betting_day": "2026-11-06",
            "keys": [row_authority_key(row, "ace_picks")]}


def _verified_status(actual=7, *, p1="p1", p2="p2"):
    return {
        "status": "win", "provider_status": "finished",
        "checked_at": "2026-11-06T14:00:00+00:00",
        "provider_home_id": p1, "provider_away_id": p2,
        "projection_stats_p1_id": p1, "projection_stats_p2_id": p2,
        "projection_stats": {"p1_aces": actual, "p2_aces": 4},
    }


class _Provider:
    def live_events(self):
        raise AssertionError("Already terminal: paid provider must not be queried")


def test_confirmed_frozen_aces_line_survives_0600_and_settles_without_api():
    frozen = _ace()
    initial = _day6(frozen)
    unmodified = deepcopy(initial)
    captured = confirmed_rollover_rows(initial, _receipt(frozen), now=DAY6)
    assert len(captured) == 1
    assert captured[0]["receipt_key"] == row_authority_key(frozen, "ace_picks")
    assert initial == unmodified

    # An empty fresh daily board is never proof that yesterday's issued
    # pre-start commitments were withdrawn.
    today = _day7()
    carried = confirmed_rollover_rows(
        today, None, {"rollover_issued_rows": captured}, now=DAY7,
    )
    assert len(carried) == 1
    tracking = feed_with_issued_rollover(today, carried, now=DAY7)
    assert today["ace_picks"] == []  # never resurface as today's member offers
    assert len(tracking["ace_picks"]) == 1
    assert tracking["ace_picks"][0]["_issued_rollover_generated_at"] == ISSUED

    old_status = {"statuses": {frozen["event_id"]: _verified_status()}}
    saved = scan_match_statuses(
        tracking, _Provider(), old_status, now=DAY7,
        issued_rollover_rows=carried,
    )
    assert saved["provider_requests"] == 0
    assert saved["statuses"][frozen["event_id"]]["status"] == "win"
    archived = settled_archive_candidates(tracking, saved["statuses"])
    assert len(archived) == 1
    pub = archived[0]["market_publications"][0]
    assert pub["publication_key"] == frozen["market_publications"][0]["publication_key"]
    assert pub["market_line"] == 5.5
    assert pub["result"]["actual_count"] == 7
    assert pub["result"]["correct"] is True
    assert pub["result"]["profit_units"] == 0.70


def test_unconfirmed_or_mutated_aces_never_enters_next_day_settlement():
    frozen = _ace()
    feed = _day6(frozen)
    assert confirmed_rollover_rows(feed, None, now=DAY6) == []
    assert confirmed_rollover_rows(
        feed, {**_receipt(frozen), "keys": []}, now=DAY6,
    ) == []
    capture = confirmed_rollover_rows(feed, _receipt(frozen), now=DAY6)
    altered = deepcopy(capture)
    altered[0]["row"]["market_publications"][0]["market_line"] = 4.5
    assert confirmed_rollover_rows(
        _day7(), None, {"rollover_issued_rows": altered}, now=DAY7,
    ) == []
    altered = deepcopy(capture)
    altered[0]["receipt_key"] = "a" * 64
    assert confirmed_rollover_rows(
        _day7(), None, {"rollover_issued_rows": altered}, now=DAY7,
    ) == []


def test_aces_missing_or_wrong_player_statistics_remain_pending_after_rollover():
    frozen = _ace()
    capture = confirmed_rollover_rows(_day6(frozen), _receipt(frozen), now=DAY6)
    tracking = feed_with_issued_rollover(_day7(), capture, now=DAY7)
    for missing in (
        {**_verified_status(), "projection_stats": {}},
        {**_verified_status(), "projection_stats_p1_id": "wrong-player"},
        {**_verified_status(), "provider_home_id": "wrong-player"},
    ):
        assert settled_archive_candidates(tracking, {frozen["event_id"]: missing}) == []
    assert confirmed_rollover_rows(
        _day7(), None, {"rollover_issued_rows": capture},
        now=datetime(2026, 11, 11, 6, tzinfo=timezone.utc),
    ) == []
