from copy import deepcopy

import pytest

from tbt.services.publication import restore_published_market_snapshots


def _feed_row(*, odds=2.10, probability=0.72, edge=0.12, ev=0.15):
    return {
        "event_id": "17201971",
        "scheduled_at": "2026-09-28T10:00:00+00:00",
        "player1": {"id": "A", "name": "Alpha", "probability": probability},
        "player2": {"id": "B", "name": "Beta", "probability": 1 - probability},
        "betting": {
            "market": "match_winner",
            "selection_id": "A",
            "selection": "Alpha",
            "odds": odds,
            "model_probability": probability,
            "edge": edge,
            "expected_value": ev,
            "betting_day": "2026-09-28",
        },
        "odds": odds,
        "probability": probability,
        "edge": edge,
        "expected_value": ev,
        "selection": "Alpha",
        "pick": "Alpha",
    }


def _legacy_publication(*, odds=1.84, probability=0.69, edge=0.08, ev=0.09):
    return {
        "schema": 1,
        "publication_key": "prime:legacy:17201971:A",
        "section": "prime",
        "market": "match_winner",
        "selection": "Alpha",
        "selection_id": "A",
        "odds": odds,
        "model_probability": probability,
        "edge": edge,
        "expected_value": ev,
        # Legacy issued rows predate betting_day persistence.
        "betting_day": None,
        "issued_at": "2026-09-28T05:55:00+00:00",
        "publication_status": "published",
    }


def test_unique_legacy_dayless_prime_snapshot_is_restored():
    current = _feed_row()
    feed = {
        "top_daily_picks": [],
        "prime_picks": [deepcopy(current)],
        "value_picks": [],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
    }
    ledger = [{
        "event_id": "17201971",
        "market_publications": [_legacy_publication()],
    }]

    restored = restore_published_market_snapshots(feed, ledger)
    card = restored["prime_picks"][0]

    assert card["betting"]["odds"] == 1.84
    assert card["betting"]["model_probability"] == 0.69
    assert card["betting"]["edge"] == 0.08
    assert card["betting"]["expected_value"] == 0.09
    assert card["odds"] == 1.84
    assert card["probability"] == 0.69
    # The current row still owns the explicit day identity; only immutable
    # issued market values are restored from the legacy snapshot.
    assert card["betting"]["betting_day"] == "2026-09-28"


def test_conflicting_legacy_dayless_prime_snapshots_still_fail_closed():
    feed = {
        "top_daily_picks": [],
        "prime_picks": [_feed_row()],
        "value_picks": [],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
    }
    ledger = [{
        "event_id": "17201971",
        "market_publications": [
            _legacy_publication(odds=1.84),
            _legacy_publication(odds=1.91),
        ],
    }]

    with pytest.raises(RuntimeError, match="prime event 17201971"):
        restore_published_market_snapshots(feed, ledger)


def test_duplicate_identical_legacy_snapshots_collapse_safely():
    snapshot = _legacy_publication()
    feed = {
        "top_daily_picks": [],
        "prime_picks": [_feed_row()],
        "value_picks": [],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
    }
    ledger = [{
        "event_id": "17201971",
        "market_publications": [deepcopy(snapshot), deepcopy(snapshot)],
    }]

    restored = restore_published_market_snapshots(feed, ledger)
    card = restored["prime_picks"][0]
    assert card["betting"]["odds"] == 1.84
    assert card["betting"]["model_probability"] == 0.69
    assert card["betting"]["betting_day"] == "2026-09-28"


def test_conflicting_legacy_snapshots_restore_first_issued_commitment():
    feed = {
        "top_daily_picks": [],
        "prime_picks": [_feed_row()],
        "value_picks": [],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
    }
    first = _legacy_publication(odds=1.84, probability=0.69, edge=0.08, ev=0.09)
    later = _legacy_publication(odds=1.91, probability=0.66, edge=0.05, ev=0.06)
    later["issued_at"] = "2026-09-28T06:05:00+00:00"
    ledger = [{
        "event_id": "17201971",
        "market_publications": [later, first],
    }]

    restored = restore_published_market_snapshots(feed, ledger)
    card = restored["prime_picks"][0]
    assert card["betting"]["odds"] == 1.84
    assert card["betting"]["model_probability"] == 0.69


def test_conflicting_legacy_snapshots_with_tied_first_issue_still_fail_closed():
    feed = {
        "top_daily_picks": [],
        "prime_picks": [_feed_row()],
        "value_picks": [],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
    }
    first = _legacy_publication(odds=1.84)
    conflict = _legacy_publication(odds=1.91)
    ledger = [{
        "event_id": "17201971",
        "market_publications": [first, conflict],
    }]

    with pytest.raises(RuntimeError, match="prime event 17201971"):
        restore_published_market_snapshots(feed, ledger)


def test_tied_conflicting_prime_can_be_quarantined_for_daily_offer_recovery():
    feed = {
        "top_daily_picks": [],
        "prime_picks": [_feed_row()],
        "value_picks": [],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
    }
    first = _legacy_publication(odds=1.84)
    conflict = _legacy_publication(odds=1.91)
    ledger = [{
        "event_id": "17201971",
        "market_publications": [first, conflict],
    }]
    quarantine = []

    restored = restore_published_market_snapshots(
        feed,
        ledger,
        quarantine_report=quarantine,
    )

    assert restored["prime_picks"] == []
    assert quarantine == [{
        "event_id": "17201971",
        "market": "match_winner",
        "section": "prime",
        "reason": "ambiguous_issued_legacy_match_winner_snapshots",
    }]


def test_tied_conflicting_value_can_be_quarantined_for_daily_offer_recovery():
    feed = {
        "top_daily_picks": [],
        "prime_picks": [],
        "value_picks": [_feed_row()],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
    }
    first = _legacy_publication(odds=1.84)
    conflict = _legacy_publication(odds=1.91)
    for publication in (first, conflict):
        publication["section"] = "value"
        publication["publication_key"] = "value:legacy:17201971:A"
    ledger = [{
        "event_id": "17201971",
        "market_publications": [first, conflict],
    }]
    quarantine = []

    restored = restore_published_market_snapshots(
        feed,
        ledger,
        quarantine_report=quarantine,
    )

    assert restored["value_picks"] == []
    assert quarantine == [{
        "event_id": "17201971",
        "market": "match_winner",
        "section": "value",
        "reason": "ambiguous_issued_legacy_match_winner_snapshots",
    }]


def test_tied_conflicting_value_remains_strict_without_quarantine_sink():
    feed = {
        "top_daily_picks": [],
        "prime_picks": [],
        "value_picks": [_feed_row()],
        "doubles_picks": [],
        "ace_picks": [],
        "sg_picks": [],
    }
    first = _legacy_publication(odds=1.84)
    conflict = _legacy_publication(odds=1.91)
    for publication in (first, conflict):
        publication["section"] = "value"
    ledger = [{
        "event_id": "17201971",
        "market_publications": [first, conflict],
    }]

    with pytest.raises(RuntimeError, match="value event 17201971"):
        restore_published_market_snapshots(feed, ledger)
