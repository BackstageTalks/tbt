"""Pre-deploy schema-2 issuance is valid for trust diagnostics only if immutable."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from audit_top_reliability import issued_snapshot, confidence, rank_band, analyze as top_audit
from audit_market_reliability import analyze as market_audit

ISSUED = "2026-10-08T10:10:00+00:00"
PREPARED = "2026-10-08T10:05:00+00:00"
QUOTE = "2026-10-08T10:03:00+00:00"
SCHEDULED = "2026-10-08T12:00:00+00:00"
NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


def fixture():
    prep = {
        "schema": 2, "source": "pre_deploy_feed",
        "prepared_at": PREPARED, "market_captured_at": QUOTE,
        "model_probability": .75, "blinq_probability": .71,
        "model_version": "frozen-version",
        "two_way_match_winner": {"player1_odds": 1.8, "player2_odds": 2.05},
        "players": {
            "player1": {"id": "a", "rank": 850},
            "player2": {"id": "b", "rank": 1150},
        },
        "quality": {
            "player1": {"surface_matches": 7},
            "player2": {"surface_matches": 9},
        },
        "stats_available": True,
        "data_depth": .86,
    }
    issued_snap = dict(prep, source="pre_deploy_feed_confirmed", confirmed_at=ISSUED)
    pub = {
        "section": "top_daily", "market": "match_winner",
        "selection_id": "a", "publication_key": "top:v2",
        "model_probability": .75, "odds": 1.8,
        "fair_implied_probability": .532,
        "issued_at": ISSUED, "publication_status": "published",
        "prepared_snapshot": prep, "issued_snapshot": issued_snap,
        "result": {"correct": True, "scheduled_at": SCHEDULED},
    }
    return {
        "event_id": "v2", "scheduled_at": SCHEDULED,
        "model_version": "outdated-current-row",
        "winner_id": "a", "raw_model_confidence": .9,
        "blinq_probability": .9, "data_depth": .99,
        "tour": "atp",
        "player1": {"id": "a", "rank": 1},
        "player2": {"id": "b", "rank": 2},
        "market_publications": [pub],
    }


def test_v2_uses_verified_published_probability_and_rank_not_mutable_row():
    row = fixture()
    pub = row["market_publications"][0]
    assert issued_snapshot(pub) is pub["issued_snapshot"]
    assert confidence(row, pub) == pytest.approx(.71)
    assert rank_band(row, "a", cutoff=1000, publication=pub) == (
        "pick_top_1000_opponent_1000_plus"
    )
    top = top_audit([row], now=NOW)
    assert top["diagnostics"]["exact_issued_evidence"] == 1
    assert top["overall"]["mean_confidence"] == pytest.approx(.71)
    assert top["subgroups"]["surface_evidence"]["both_5_plus"]["wins"] == 1
    market = market_audit([row], now=NOW)
    assert market["sections"]["top_daily"]["exact_probability_snapshots"] == 1
    assert market["sections"]["top_daily"]["overall"]["mean_confidence"] == pytest.approx(.71)
    assert market["sections"]["top_daily"]["by_model_version"]["frozen-version"]["wins"] == 1


@pytest.mark.parametrize("mutation", [
    "prepared_missing", "snapshot_changed", "model_mismatch", "confirmation_late",
    "prepared_after_issuance", "quote_after_prepared", "one_sided_quote",
])
def test_v2_rejects_modified_or_hindsight_snapshot(mutation):
    row = fixture()
    pub = row["market_publications"][0]
    if mutation == "prepared_missing":
        del pub["prepared_snapshot"]
    elif mutation == "snapshot_changed":
        pub["issued_snapshot"]["blinq_probability"] = .99
    elif mutation == "model_mismatch":
        pub["issued_snapshot"]["model_probability"] = .83
        pub["prepared_snapshot"]["model_probability"] = .83
    elif mutation == "confirmation_late":
        pub["issued_snapshot"]["confirmed_at"] = SCHEDULED
    elif mutation == "prepared_after_issuance":
        future = "2026-10-08T10:11:00+00:00"
        pub["prepared_snapshot"]["prepared_at"] = future
        pub["issued_snapshot"]["prepared_at"] = future
    elif mutation == "quote_after_prepared":
        future = "2026-10-08T10:06:00+00:00"
        pub["prepared_snapshot"]["market_captured_at"] = future
        pub["issued_snapshot"]["market_captured_at"] = future
    elif mutation == "one_sided_quote":
        pub["prepared_snapshot"]["two_way_match_winner"]["player2_odds"] = None
    assert issued_snapshot(pub) is None
    assert confidence(row, pub) is None


def test_legacy_snapshot_still_supported_without_v2_fields():
    row = fixture()
    pub = row["market_publications"][0]
    pub["issued_snapshot"] = {
        "schema": 1, "source": "deployed_feed_at_issuance",
        "captured_at": ISSUED, "model_probability": .75,
        "blinq_probability": .7,
        "ranks": {"player1": {"id": "a", "rank": 300},
                  "player2": {"id": "b", "rank": 700}},
    }
    pub.pop("prepared_snapshot")
    assert issued_snapshot(pub) is not None
    assert confidence(row, pub) == pytest.approx(.7)
    assert rank_band(row, "a", cutoff=500, publication=pub) == (
        "pick_top_500_opponent_500_plus"
    )
