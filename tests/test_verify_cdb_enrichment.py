"""Offline fail-closed contract tests for enriching existing canonical matches."""
from copy import deepcopy

import pytest
from scripts.verify_cdb_enrichment import check_reports, verify_partition_records


class FakeRecord:
    def __init__(self, row):
        self.match_id = row["match_id"]
        self.row = row

    def model_dump(self, mode="json"):
        return deepcopy(self.row)


def record(mid, stats=None, winner="a", payload=None):
    return FakeRecord({"match_id": mid, "winner_id": winner, "player1_id": "a",
                       "player2_id": "b", "scheduled_at": "2024-01-01T10:00:00+00:00",
                       "stats": stats or {}, "provider_payload": payload or {}})


def report():
    return (
        {"canonical_rows": 100, "production_mutated": False, "api_requests": 0,
         "counts": {"staged_matches": 1}},
        {"stage_rows": 1, "production_mutated": False, "api_requests": 0,
         "counts": {"updated": 1}, "changed_years": [2024],
         "quality_ready_before": 55, "quality_ready_after": 56,
         "quality_ready_added": 1},
        {"m1": {"incoming_stats": {"p1_aces": 4}}},
    )


def test_prewrite_gate_accepts_verified_nonzero_delta():
    link, dry, stage = report()
    assert check_reports(link, dry, stage) == 1
    write = dict(dry, local_partitions_written=True)
    assert check_reports(link, dry, stage, write) == 1


@pytest.mark.parametrize("key,value", [
    ("identity_changed", 1), ("stat_conflicts", 1),
    ("invalid_provenance", 1), ("baseline_stats_changed", 1),
])
def test_rejects_dry_run_conflicts(key, value):
    link, dry, stage = report()
    dry["counts"][key] = value
    with pytest.raises(ValueError, match="Fail-closed"):
        check_reports(link, dry, stage)


def test_fail_closed_on_mismatched_stage_and_writer():
    link, dry, stage = report()
    with pytest.raises(ValueError, match="mismatch"):
        check_reports(link, dict(dry, stage_rows=2), stage)
    with pytest.raises(ValueError, match="mismatch"):
        check_reports(link, dry, stage, dict(dry, local_partitions_written=True, changed_years=[2025]))


def test_reads_only_missing_stats_and_leaves_unstaged_match_intact():
    before = [record("m1", {"p2_aces": 2}), record("m2", {"p1_aces": 1})]
    after = [record("m1", {"p1_aces": 4, "p2_aces": 2}), record("m2", {"p1_aces": 1})]
    stage = {"m1": {"incoming_stats": {"p1_aces": 4}}}
    assert verify_partition_records(before, after, stage) == {"m1"}


def test_rejects_unstaged_modification_and_identity_mutation():
    before = [record("m1", {"p2_aces": 2}), record("m2", {"p1_aces": 1})]
    stage = {"m1": {"incoming_stats": {"p1_aces": 4}}}
    with pytest.raises(ValueError, match="Unstaged"):
        verify_partition_records(before, [record("m1", {"p2_aces": 2, "p1_aces": 4}),
                                         record("m2", {"p1_aces": 10})], stage)
    with pytest.raises(ValueError, match="Immutable"):
        verify_partition_records(before, [record("m1", {"p2_aces": 2, "p1_aces": 4}, winner="b"),
                                         record("m2", {"p1_aces": 1})], stage)


def test_rejects_overwriting_old_stats_or_unverified_new_keys():
    old = [record("m1", {"p2_aces": 2})]
    stage = {"m1": {"incoming_stats": {"p1_aces": 4}}}
    for invalid in ({"p2_aces": 3, "p1_aces": 4}, {"p2_aces": 2, "p1_aces": 4, "p2_return_points_won": .5}):
        with pytest.raises(ValueError, match="stats changed"):
            verify_partition_records(old, [record("m1", invalid)], stage)


def test_zero_delta_when_linker_candidates_already_exist_in_cdb():
    link, dry, _ = report()
    dry["stage_rows"] = 0
    dry["counts"]["updated"] = 0
    dry["changed_years"] = []
    dry["quality_ready_after"] = dry["quality_ready_before"]
    dry["quality_ready_added"] = 0
    assert check_reports(link, dry, {}) == 0
    write = dict(dry, local_partitions_written=False)
    assert check_reports(link, dry, {}, write) == 0


def test_zero_stage_does_not_hide_a_mismatched_write():
    link, dry, _ = report()
    dry["stage_rows"] = 0
    dry["counts"]["updated"] = 0
    dry["changed_years"] = []
    dry["quality_ready_after"] = dry["quality_ready_before"]
    dry["quality_ready_added"] = 0
    with pytest.raises(ValueError, match="Local write not confirmed"):
        check_reports(link, dry, {}, dict(dry, local_partitions_written=True))
    with pytest.raises(ValueError, match="Stage count mismatch"):
        check_reports(link, dict(dry, stage_rows=1), {})
