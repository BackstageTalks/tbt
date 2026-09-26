"""Regression for today's two real PropLine ACES cards lost to legacy publication-key collision."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from tbt.services.engine import reconcile_ledger
from tbt.services.market_selection import annotate_market_publication_candidates
from tbt.services.publication import (
    restore_published_market_snapshots, validate_market_publication_candidate,
)

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
START = (NOW + timedelta(hours=7)).isoformat()


def _fixture():
    return {
        "event_id": "17108577", "scheduled_at": START,
        "player1": {"id": "A", "name": "Player Alpha", "probability": .74},
        "player2": {"id": "B", "name": "Player Beta", "probability": .26},
        "winner_id": "A", "confidence": .74,
        "model_version": "test-v1", "created_at": NOW.isoformat(),
    }


def _ace():
    return {
        **_fixture(), "market": "aces", "selection_id": "A",
        "pick": "Player Alpha Over 4.5 Aces",
        "selection": "Player Alpha Over 4.5 Aces",
        "price_contract": "player_total_ou",
        "market_line": 4.5, "ou_side": "over",
        "projection": 6.0, "opponent_projection": 2.0,
        "projection_scope": "player", "projection_metric": "aces",
        "projection_confidence": .78, "projection_label": "Hráč · Aces O/U",
        "odds": 2.0, "price_status": "priced_projection",
        "provider_id": 2, "captured_at": NOW.isoformat(),
        "odds_source": "propline",
    }


def _old_issued():
    return {
        "publication_key": "ace:projection:aces:player:17108577:A",
        "selection_key": "projection:aces:player:17108577:A",
        "section": "ace", "primary_section": "ace", "market": "aces",
        "selection_id": "A", "selection": "Player Alpha",
        "projection": 5.2, "opponent_projection": 2.4,
        "projection_scope": "player", "projection_metric": "aces",
        "projection_confidence": .7, "projection_label": "Hráč · Esá",
        "odds": None, "model_probability": None,
        "edge": None, "expected_value": None, "betting_day": None,
        "issued_at": NOW.isoformat(), "publication_status": "published",
        "price_status": "projection_only",
    }


def test_player_total_ou_is_distinct_from_issued_legacy_same_player():
    base = _fixture()
    ace = _ace()
    annotated = annotate_market_publication_candidates([base], ace_picks=[ace])
    pending = [p for p in annotated[0]["market_publication_candidates"] if p["market"] == "aces"]
    assert len(pending) == 1
    assert pending[0]["selection_key"].endswith(":total:over:4.5")
    assert pending[0]["publication_key"] != _old_issued()["publication_key"]

    previous = {**base, "market_publications": [_old_issued()]}
    merged = reconcile_ledger([previous], annotated, [], NOW)
    assert len(merged) == 1
    publications = merged[0]["market_publications"]
    assert len(publications) == 2
    assert publications[0] == _old_issued()
    assert publications[1]["publication_status"] == "pending"
    assert publications[1]["odds_source"] == "propline"

    feed = {"ace_picks": [ace], "sg_picks": []}
    quarantined = []
    restored = restore_published_market_snapshots(
        feed, merged, quarantine_report=quarantined,
    )
    assert quarantined == []
    assert restored["ace_picks"] == [ace]
    assert validate_market_publication_candidate(restored, merged) == 1


def test_legacy_superiority_publication_key_is_unchanged():
    ace = _ace()
    ace["price_contract"] = "player_superiority"
    ace.pop("ou_side")
    ace.pop("market_line")
    rows = annotate_market_publication_candidates([_fixture()], ace_picks=[ace])
    publication = rows[0]["market_publication_candidates"][0]
    assert publication["publication_key"] == "ace:projection:aces:player:17108577:A"


@pytest.mark.parametrize("side,line", [("", 4.5), ("over", None), ("under", -1)])
def test_invalid_player_total_contract_fails_closed(side, line):
    ace = _ace()
    ace["ou_side"] = side
    ace["market_line"] = line
    with pytest.raises(ValueError, match="O/U"):
        annotate_market_publication_candidates([_fixture()], ace_picks=[ace])


def test_distinct_over_under_and_lines_do_not_overwrite_each_other():
    first = _ace()
    other = deepcopy(first)
    other["ou_side"] = "under"
    other["market_line"] = 5.5
    rows = annotate_market_publication_candidates([_fixture()], ace_picks=[first, other])
    pubs = rows[0]["market_publication_candidates"]
    keys = [p["publication_key"] for p in pubs]
    assert len(keys) == len(set(keys)) == 2
