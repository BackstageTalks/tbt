"""No-network identity readback unit checks."""
from copy import deepcopy

import pytest

from scripts.verify_native_event_ids import verify_rows
from tests.test_recover_native_event_id import Match, native


def expected():
    return {
        "target": {
            "tour": "wta", "year": 2025, "event_id": "900",
            "home": "111", "away": "222", "stats_before": {},
        },
    }


def persisted():
    match = native("900")
    match.match_id = "target"
    return match


def test_exact_native_identity_and_unchanged_stats():
    assert verify_rows([persisted()], expected()) == {"target"}


def test_reject_changed_stats():
    row = persisted()
    row.stats["p1_aces"] = 6
    with pytest.raises(ValueError, match="statistics"):
        verify_rows([row], expected())


def test_reject_wrong_player():
    row = persisted()
    row.player2_id = "different"
    with pytest.raises(ValueError, match="identity"):
        verify_rows([row], expected())


def test_reject_missing_witness():
    row = persisted()
    row.provider_payload.pop("_tbt_event_identity")
    with pytest.raises(ValueError, match="identity"):
        verify_rows([row], expected())


def test_reject_duplicate_canonical_id():
    with pytest.raises(ValueError, match="Repeated"):
        verify_rows([persisted(), deepcopy(persisted())], expected())
