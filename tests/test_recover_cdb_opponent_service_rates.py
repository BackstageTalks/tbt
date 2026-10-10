"""Exact historical service/return complement recovery safety regression tests."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from scripts.recover_cdb_opponent_service_rates import stage, write_local, verify_readback
from tbt.schemas import MatchRecord


def match(idx="one", stats=None):
    return MatchRecord(
        match_id=idx, tour="atp", scheduled_at=datetime(2024, 8, 3, tzinfo=timezone.utc),
        player1_id="p1", player1_name="One", player2_id="p2", player2_name="Two",
        tournament="US Open", winner_id="p1",
        status="completed", stats=stats or {},
    )


def test_exact_complement_can_enrich_without_touching_existing_facts():
    original = match(stats={"p1_service_points_won": 0.62,
                            "p2_return_points_won": 0.38,
                            "p2_service_points_won": 0.58,
                            "p1_aces": 7})
    staged, counts = stage([original])
    assert counts["staged_matches"] == 1
    assert counts["new_stat_values"] == 1
    assert staged[0]["additions"] == {"p1_return_points_won": pytest.approx(0.42)}
    local = deepcopy(original)
    assert write_local([local], staged) == [2024]
    assert local.stats["p1_aces"] == 7
    assert local.stats["p1_return_points_won"] == pytest.approx(0.42)
    readback = verify_readback([original], [local], staged)
    assert readback["new_stat_values"] == 1
    assert readback["existing_values_overwritten"] == 0


def test_empty_stats_cannot_be_imputed():
    rows, counts = stage([match(stats={"p1_aces": 4})])
    assert rows == []
    assert counts.get("new_stat_values", 0) == 0


def test_local_import_refuses_changed_stat_or_identity():
    original = match(stats={"p1_service_points_won": 0.62})
    staged, _ = stage([original])
    changed = deepcopy(original)
    changed.stats["p1_aces"] = 6
    with pytest.raises(ValueError, match="changed since dry-run"):
        write_local([changed], staged)
    other = deepcopy(original)
    other.player2_name = "Different"
    with pytest.raises(ValueError, match="changed since dry-run"):
        write_local([other], staged)
    # Changing the winning player ID invalidates completion, which must fail
    # even earlier than the canonical snapshot hash check.
    other = deepcopy(original)
    other.player1_id = "different"
    with pytest.raises(ValueError, match="Staged identity missing or match not completed"):
        write_local([other], staged)


def test_wrong_derived_value_and_duplicate_stage_rejected():
    original = match(stats={"p1_service_points_won": 0.62})
    staged, _ = stage([original])
    changed = deepcopy(staged)
    changed[0]["additions"]["p2_return_points_won"] = 0.9
    with pytest.raises(ValueError, match="not reproducible"):
        write_local([original], changed)
    with pytest.raises(ValueError, match="Duplicate"):
        write_local([original], staged + staged)


def test_readback_rejects_unstaged_stat_and_canonical_field_mutation():
    original = match(stats={"p1_service_points_won": 0.62})
    staged, _ = stage([original])
    after = deepcopy(original)
    write_local([after], staged)
    after.stats["p1_aces"] = 9
    with pytest.raises(ValueError, match="Unstaged"):
        verify_readback([original], [after], staged)
    after = deepcopy(original)
    write_local([after], staged)
    after.player2_name = "Mutated"
    with pytest.raises(ValueError, match="Unstaged"):
        verify_readback([original], [after], staged)


def test_not_completed_or_future_matches_never_used():
    # No need to construct speculative in-play features. Future records are
    # categorically excluded even if a stale feed labels them completed.
    future = match(stats={"p1_service_points_won": 0.7})
    staged, counts = stage([future], as_of=datetime(2023, 1, 1, tzinfo=timezone.utc))
    assert staged == []
    assert counts["noncompleted_or_future"] == 1


def test_conflicting_direct_observations_are_quarantined_without_overwrite():
    original = match(stats={"p1_service_points_won": 0.62,
                            "p2_return_points_won": 0.40,
                            "p2_service_points_won": 0.59})
    records, summary = stage([original])
    assert records == []
    assert summary["contradictory_observed_rates"] == 1
