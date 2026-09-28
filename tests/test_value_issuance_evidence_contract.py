"""Forward Value-publication evidence must be complete and immutable."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from tbt.services.market_selection import (
    annotate_market_publication_candidates,
    select_market_sections,
)
from tbt.services.publication import (
    confirm_market_publications,
    validate_market_publication_candidate,
)


def value_row():
    return {
        "id": "m-value-evidence",
        "event_id": "value-evidence",
        "scheduled_at": "2026-09-29T15:00:00+00:00",
        "tour": "ATP",
        "tournament": "Evidence Open",
        "surface": "hard",
        "round": "R16",
        "competition": "ATP",
        "player1": {"id": "A", "name": "Alpha", "probability": .66, "rank": 120},
        "player2": {"id": "B", "name": "Beta", "probability": .34, "rank": 180},
        "winner_id": "A",
        "confidence": .66,
        "data_depth": .82,
        "quality": {
            "player1": {"matches": 40, "surface_matches": 12},
            "player2": {"matches": 42, "surface_matches": 11},
            "surface_known": True,
        },
        "signals": [],
        "model_version": "test-value-evidence",
        "created_at": "2026-09-28T08:00:00+00:00",
        "issued_at": None,
        "publication_status": "pending",
        "result": None,
        "betting": {
            "market": "match_winner",
            "selection": "Alpha",
            "selection_id": "A",
            "odds": 1.90,
            "fair_implied_probability": .51,
            "model_probability": .66,
            "blinq_probability": .64,
            "probability_reliability": .82,
            "edge": .15,
            "expected_value": .254,
            "provider_id": 1,
            "captured_at": "2026-09-28T08:00:00+00:00",
            "betting_day": "2026-09-28",
        },
        "match_winner_market": {
            "player1_odds": 1.90,
            "player2_odds": 1.95,
            "player1_implied_probability": .51,
            "player2_implied_probability": .49,
        },
    }


def build():
    candidate = annotate_market_publication_candidates([value_row()])[0]
    sections = select_market_sections([candidate])
    assert len(sections["value_picks"]) == 1
    ledger = [{**candidate, "market_publications": candidate["market_publication_candidates"]}]
    ledger[0].pop("market_publication_candidates", None)
    feed = {
        "top_daily_picks": sections["top_daily_picks"],
        "prime_picks": sections["prime_picks"],
        "value_picks": sections["value_picks"],
    }
    return ledger, feed


def test_complete_value_evidence_validates_and_freezes_exact_issue_snapshot():
    ledger, feed = build()
    assert validate_market_publication_candidate(feed, ledger) == 1

    issued, count = confirm_market_publications(
        ledger, feed, datetime(2026, 9, 28, 9, tzinfo=timezone.utc)
    )
    assert count == 1
    publication = next(
        p for p in issued[0]["market_publications"] if p["section"] == "value"
    )
    assert publication["publication_status"] == "published"
    assert publication["fair_implied_probability"] == pytest.approx(.51)
    snapshot = publication["issued_snapshot"]
    assert snapshot["source"] == "deployed_feed_at_issuance"
    assert snapshot["captured_at"] == publication["issued_at"]
    assert snapshot["model_probability"] == pytest.approx(.66)
    assert snapshot["quality"]["player1"]["surface_matches"] == 12
    assert snapshot["quality"]["player2"]["surface_matches"] == 11
    assert snapshot["data_depth"] == pytest.approx(.82)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda row: row["betting"].pop("fair_implied_probability"), "missing_two_sided_fair_probability"),
        (lambda row: row.pop("quality"), "missing_quality_snapshot"),
        (lambda row: row["quality"]["player2"].pop("surface_matches"), "missing_surface_sample"),
        (lambda row: row.pop("data_depth"), "missing_data_depth"),
        (lambda row: row["betting"].pop("odds"), "missing_real_odds"),
    ],
)
def test_incomplete_value_evidence_fails_before_deployment(mutate, reason):
    ledger, feed = build()
    broken = deepcopy(feed)
    mutate(broken["value_picks"][0])
    with pytest.raises(RuntimeError, match=reason):
        validate_market_publication_candidate(broken, ledger)
