"""Regress the 2026-11-06 Safonov leak at the member-serving boundary."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from tbt.services.issued_authority import (
    build_confirmed_authority,
    filter_unissued_offers,
    row_authority_key,
    validate_authority,
)


NOW = datetime(2026, 11, 6, 13, 0, tzinfo=timezone.utc)


def pick(event, *, price=1.75, probability=.82, start="2026-11-06T16:00:00+00:00"):
    return {
        "event_id": event,
        "id": "prediction-" + event,
        "scheduled_at": start,
        "created_at": "2026-11-06T06:20:00+00:00",
        "model_version": "7.2.1",
        "player1": {"id": "p1-" + event, "probability": probability},
        "player2": {"id": "p2-" + event, "probability": 1 - probability},
        "winner_id": "p1-" + event,
        "confidence": probability,
        "betting": {
            "market": "match_winner",
            "selection_id": "p1-" + event,
            "odds": price,
            "model_probability": probability,
            "edge": .10,
            "expected_value": .20,
            "betting_day": "2026-11-06",
        },
    }


def ledger_entry(row, *, issued=True):
    bet = row["betting"]
    issued_at = "2026-11-06T06:27:00+00:00" if issued else None
    publication = {
        "section": "top_daily", "market": "match_winner",
        "selection_id": bet["selection_id"], "odds": bet["odds"],
        "model_probability": bet["model_probability"], "edge": bet["edge"],
        "expected_value": bet["expected_value"], "betting_day": bet["betting_day"],
        "issued_at": issued_at,
        "publication_status": "published" if issued else "expired_unpublished",
    }
    return {
        **{key: deepcopy(row[key]) for key in (
            "event_id", "id", "scheduled_at", "created_at", "model_version",
            "player1", "player2", "winner_id", "confidence",
        )},
        "issued_at": issued_at,
        "publication_status": "published" if issued else "expired_unpublished",
        "market_publications": [publication],
    }


def test_safonov_pending_expires_but_never_becomes_member_top():
    a = pick("van-herck", probability=.902, price=2.18)
    b = pick("nakashima", probability=.765, price=1.77)
    c = pick("sahtali", probability=.755, price=1.65)
    safonov = pick("17497459", probability=.8304140127388535, price=3.70,
                   start="2026-11-06T06:30:00+00:00")
    feed = {
        "schema": 1, "generated_at": "2026-11-06T06:24:57+00:00",
        "upcoming": [a, b, c, safonov],
        "top_daily_picks": [a, b, c, safonov],
        "results": [{"event_id": "prior-settled", "result": {"correct": True}}],
    }
    ledger = [ledger_entry(row) for row in (a, b, c)]
    ledger.append(ledger_entry(safonov, issued=False))
    allowed = build_confirmed_authority(feed, ledger, now=NOW)
    assert allowed["confirmed_only"] is True
    assert len(allowed["keys"]) == 6  # 3 confirmed TOP + 3 confirmed future predictions
    assert row_authority_key(safonov, "top_daily_picks") not in allowed["keys"]

    from tbt.services.feed import visible_feed
    serving = filter_unissued_offers(visible_feed(feed, now=NOW), allowed)
    assert [x["event_id"] for x in serving["top_daily_picks"]] == [
        "van-herck", "nakashima", "sahtali",
    ]
    assert "17497459" not in {x["event_id"] for x in serving["upcoming"]}
    assert serving["results"] == feed["results"]
    assert len(feed["top_daily_picks"]) == 4  # no destructive rewrite
    assert ledger[-1]["market_publications"][0]["issued_at"] is None


def test_no_confirmed_authority_fails_closed_and_preserves_results():
    candidate = pick("candidate")
    feed = {"daily_offer_day": "2026-11-06",
            "top_daily_picks": [candidate],
            "upcoming": [candidate],
            "results": [{"event_id": "historical"}]}
    visible = filter_unissued_offers(feed, None)
    assert visible["top_daily_picks"] == []
    assert visible["upcoming"] == []
    assert visible["results"] == feed["results"]
    assert visible["publication_authority_status"] == "unavailable"


def test_existing_issued_pick_remains_after_start_during_same_day():
    started = pick("issued-earlier", start="2026-11-06T07:30:00+00:00")
    feed = {
        "schema": 1, "generated_at": "2026-11-06T06:20:00+00:00",
        "upcoming": [started], "top_daily_picks": [started],
    }
    manifest = build_confirmed_authority(feed, [ledger_entry(started)], now=NOW)
    from tbt.services.feed import visible_feed
    offered = filter_unissued_offers(visible_feed(feed, now=NOW), manifest)
    assert [r["event_id"] for r in offered["top_daily_picks"]] == ["issued-earlier"]
    assert offered["upcoming"] == []


def test_authority_is_exact_price_side_and_model_not_just_event_id():
    correct = pick("match-1")
    feed = {"schema": 1, "generated_at": "2026-11-06T06:20:00+00:00",
            "upcoming": [], "top_daily_picks": [correct]}
    manifest = build_confirmed_authority(feed, [ledger_entry(correct)], now=NOW)
    changed = deepcopy(correct)
    changed["betting"]["odds"] = 3.70
    changed["model_version"] = "other-model"
    from tbt.services.feed import visible_feed
    offered = filter_unissued_offers(visible_feed({**feed, "top_daily_picks": [changed]}, now=NOW), manifest)
    assert offered["top_daily_picks"] == []
    assert correct["betting"]["odds"] == 1.75


def test_sync_fails_on_forged_authority_or_other_generation():
    row = pick("allowed")
    feed = {"schema": 1, "generated_at": "2026-11-06T06:20:00+00:00",
            "upcoming": [], "top_daily_picks": [row]}
    manifest = build_confirmed_authority(feed, [ledger_entry(row)], now=NOW)
    assert validate_authority(manifest, feed, now=NOW) is manifest
    fake = deepcopy(manifest)
    fake["keys"] = ["a" * 64]
    with pytest.raises(ValueError, match="absent"):
        validate_authority(fake, feed, now=NOW)
    fake = deepcopy(manifest)
    fake["betting_day"] = "2026-11-05"
    with pytest.raises(ValueError, match="day"):
        validate_authority(fake, feed, now=NOW)
    fake = deepcopy(manifest)
    fake["confirmed_only"] = False
    with pytest.raises(ValueError, match="Unconfirmed"):
        validate_authority(fake, feed, now=NOW)
