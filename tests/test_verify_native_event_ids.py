"""Offline remote-readback identity controls."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.verify_native_event_ids import verify_rows


def expected():
    return {"target": {
        "tour": "wta", "year": 2025, "event_id": "900",
        "home": "111", "away": "222", "stats_before": {},
    }}


def persisted():
    return SimpleNamespace(
        match_id="target", tour="wta",
        player1_id="111", player2_id="222", winner_id="111", stats={},
        scheduled_at=datetime(2025, 4, 10, tzinfo=timezone.utc),
        provider_payload={
            "_tbt_provider_event_id": "900",
            "_tbt_event_identity": {
                "event_id": "900", "home": "111", "away": "222",
                "status": "finished",
            },
        },
    )


def test_native_identity_and_original_stats():
    assert verify_rows([persisted()], expected()) == {"target"}


def test_reject_changed_statistics():
    row = persisted()
    row.stats["p1_aces"] = 6
    with pytest.raises(ValueError, match="statistics"):
        verify_rows([row], expected())


def test_reject_different_participant():
    row = persisted()
    row.player2_id = "different"
    with pytest.raises(ValueError, match="identity"):
        verify_rows([row], expected())


def test_reject_absent_provider_witness():
    row = persisted()
    row.provider_payload.pop("_tbt_event_identity")
    with pytest.raises(ValueError, match="identity"):
        verify_rows([row], expected())


def test_reject_duplicate_canonical_row():
    with pytest.raises(ValueError, match="Repeated"):
        verify_rows([persisted(), deepcopy(persisted())], expected())
