"""Exact historical service/return complement recovery safety regression tests."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
import hashlib
import json
import pandas as pd
from tbt.data.history_snapshot import load_snapshot, update_year_manifest, write_snapshot

from scripts.recover_cdb_opponent_service_rates import stage, write_local, verify_readback, write_exact_stats_partition
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


def test_exact_stats_parquet_patch_preserves_unstaged_rows_and_provenance(tmp_path):
    first = match("verified", stats={"p1_service_points_won": 0.62})
    other = match("untouched", stats={"p1_aces": 7.0})
    path = tmp_path / "history-2024.parquet"
    meta = write_snapshot([first, other], path)
    update_year_manifest(tmp_path, 2024, meta)
    # Extra unrecognized context must not be deleted by a stats-only importer.
    frame = pd.read_parquet(path)
    frame.loc[frame.match_id == "untouched", "provider_context_json"] = json.dumps({
        "legacy_context": {"important": "keep"},
    })
    frame.to_parquet(path, engine="pyarrow", compression="zstd", index=False)
    update_year_manifest(tmp_path, 2024, {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size, "rows": 2,
    })
    before = load_snapshot(path)
    original_frame = pd.read_parquet(path)
    staged, count = stage([first, other])
    assert count["staged_matches"] == 1
    write_exact_stats_partition(tmp_path, 2024, staged)
    after_frame = pd.read_parquet(path)
    assert original_frame.loc[original_frame.match_id == "untouched"].equals(
        after_frame.loc[after_frame.match_id == "untouched"]
    )
    assert after_frame.columns.tolist() == original_frame.columns.tolist()
    check = verify_readback(before, load_snapshot(path), staged)
    assert check["enriched_matches"] == 1
    assert check["existing_values_overwritten"] == 0
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        json.loads((tmp_path / "history_manifest.json").read_text())
        ["years"]["2024"]["sha256"]
    )


def test_exact_stats_patch_refuses_changed_stage_without_disk_mutation(tmp_path):
    original = match(stats={"p1_service_points_won": 0.62})
    path = tmp_path / "history-2024.parquet"
    meta = write_snapshot([original], path)
    update_year_manifest(tmp_path, 2024, meta)
    staged, _ = stage([original])
    bad = deepcopy(staged)
    bad[0]["additions"]["p2_return_points_won"] = 0.9
    original_bytes = path.read_bytes()
    with pytest.raises(ValueError, match="reproducible"):
        write_exact_stats_partition(tmp_path, 2024, bad)
    assert path.read_bytes() == original_bytes



def test_all_first_second_and_total_rate_complements_preserve_orientation():
    original = match(stats={
        "p1_first_serve_win": 0.75,
        "p2_second_return_win": 0.61,
        "p2_service_points_won": 0.58,
    })
    staged, counts = stage([original])
    assert counts["staged_matches"] == 1
    assert counts["new_stat_values"] == 3
    additions = staged[0]["additions"]
    assert set(additions) == {
        "p2_first_return_win", "p1_second_serve_win", "p1_return_points_won"
    }
    assert additions["p2_first_return_win"] == pytest.approx(0.25)
    assert additions["p1_second_serve_win"] == pytest.approx(0.39)
    assert additions["p1_return_points_won"] == pytest.approx(0.42)
    assert "p1_first_return_win" not in additions  # Never same-side substitution.
    persisted = deepcopy(original)
    assert write_local([persisted], staged) == [2024]
    assert verify_readback([original], [persisted], staged)["new_stat_values"] == 3


def test_both_tours_player_sides_have_all_six_recovery_pairs():
    from scripts.recover_cdb_opponent_service_rates import PAIRS, RECOVERABLE
    assert len(PAIRS) == 6 and len(RECOVERABLE) == 12
    original = match(stats={service: 0.8 for service, _ in PAIRS})
    staged, counts = stage([original])
    assert counts["new_stat_values"] == 6
    assert staged[0]["additions"] == {
        ret: pytest.approx(0.2) for _, ret in PAIRS
    }


def test_first_or_second_rate_conflict_blocks_entire_match():
    original = match(stats={
        "p1_first_serve_win": 0.70,
        "p2_first_return_win": 0.32,
        "p2_service_points_won": 0.65,  # Safe in isolation; must still skip.
    })
    staged, counts = stage([original])
    assert staged == []
    assert counts["contradictory_observed_rates"] == 1


@pytest.mark.parametrize("bad", [True, -0.1, 1.1, 70, "70%", float("inf"), float("nan")])
def test_invalid_first_second_or_return_rate_never_imputed(bad):
    original = match(stats={
        "p1_first_serve_win": bad,
        "p2_service_points_won": 0.64,
    })
    staged, counts = stage([original])
    assert staged == []
    assert counts["contradictory_observed_rates"] == 1


def test_changed_first_second_evidence_invalidates_stage():
    original = match(stats={"p2_second_return_win": 0.31})
    staged, _ = stage([original])
    changed = deepcopy(original)
    changed.stats["p2_second_return_win"] = 0.32
    with pytest.raises(ValueError, match="changed since dry-run"):
        write_local([changed], staged)
    changed = deepcopy(original)
    changed.stats["p1_second_serve_win"] = 0.75
    with pytest.raises(ValueError, match="changed since dry-run"):
        write_local([changed], staged)


def test_cdb_historical_pre_1990_year_stages_only_verified_nulls():
    historical = match(stats={"p1_first_serve_win": 0.71})
    historical.scheduled_at = datetime(1981, 6, 3, tzinfo=timezone.utc)
    staged, counts = stage([historical], as_of=datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert counts["new_stat_values"] == 1
    assert staged[0]["utc_year"] == 1981
    assert staged[0]["additions"] == {"p2_first_return_win": pytest.approx(0.29)}
    persisted = deepcopy(historical)
    assert write_local([persisted], staged) == [1981]
    assert verify_readback([historical], [persisted], staged)["new_stat_values"] == 1


def test_opt_in_pairwise_quarantines_only_conflicting_rate_pair():
    original=match(stats={
        "p1_service_points_won": 0.62,
        "p1_first_return_win": 0.80,
        "p2_first_serve_win": 0.50,
        "p1_aces": 0.0,
    })
    blocked, strict_counts=stage([original])
    assert blocked == [] and strict_counts["contradictory_observed_rates"] == 1
    rows, counts=stage([original],pairwise=True)
    assert counts["staged_matches"] == 1
    assert counts["new_stat_values"] == 1
    assert counts["conflicting_rate_pairs_quarantined"] == 1
    assert rows[0]["additions"] == {"p2_return_points_won": pytest.approx(0.38)}
    after=deepcopy(original)
    assert write_local([after],rows)==[2024]
    assert after.stats["p2_first_serve_win"] == 0.50
    assert after.stats["p1_first_return_win"] == 0.80
    assert after.stats["p1_aces"] == 0.0
    assert verify_readback([original],[after],rows)["existing_values_overwritten"] == 0
    again, second_counts=stage([after],pairwise=True)
    assert again == [] and second_counts.get("new_stat_values",0) == 0


def test_opt_in_pairwise_refuses_invalid_direct_rates_and_malicious_stage():
    original=match(stats={"p1_service_points_won": 0.62,
                          "p1_first_return_win": 1.3,
                          "p2_first_serve_win": 0.5})
    rows,counts=stage([original],pairwise=True)
    assert len(rows)==1 and counts["conflicting_rate_pairs_quarantined"]>=1
    assert rows[0]["additions"]=={"p2_return_points_won": pytest.approx(0.38)}
    forged=deepcopy(rows)
    forged[0]["additions"]["p2_return_points_won"]=0.999
    with pytest.raises(ValueError,match="not reproducible"):
        write_local([deepcopy(original)],forged)


def test_opt_in_pairwise_exact_parquet_patch_and_idempotence(tmp_path):
    original=match(stats={"p1_service_points_won":0.62,
                          "p2_first_serve_win":0.5,"p1_first_return_win":0.8})
    untouched=match("other",stats={"p2_aces":4.0})
    path=tmp_path/"history-2024.parquet"
    meta=write_snapshot([original,untouched],path)
    update_year_manifest(tmp_path,2024,meta)
    before=load_snapshot(path)
    frame_before=pd.read_parquet(path)
    rows,_=stage(before,pairwise=True)
    assert len(rows)==1
    write_exact_stats_partition(tmp_path,2024,rows)
    after=load_snapshot(path)
    assert verify_readback(before,after,rows)["new_stat_values"]==1
    frame_after=pd.read_parquet(path)
    assert frame_before.loc[frame_before.match_id=="other"].equals(
           frame_after.loc[frame_after.match_id=="other"])
    assert stage(after,pairwise=True)[0]==[]


def test_identity_safety_aggregate_excludes_private_match_and_event_ids():
    from scripts.recover_cdb_opponent_service_rates import identity_safety_aggregate
    original = {
        "input_rows": 100, "rows_after_proven_merges": 98, "output_rows": 96,
        "merged_rows_removed": 2, "quarantined_rows": 2, "changed": True,
        "duplicate_match_ids": ["private-match-id"],
        "duplicate_provider_event_ids": ["private-event-id"],
        "affected_years": [2026],
        "quarantine": [{"match_id": "private-match-id", "reason": "collision"}],
    }
    report = identity_safety_aggregate(original)
    assert report["status"] == "IDENTITY_REVIEW_REQUIRED"
    assert report["merged_rows_removed"] == 2
    assert report["quarantined_rows"] == 2
    assert report["duplicate_match_id_count"] == 1
    assert report["duplicate_provider_event_id_count"] == 1
    assert report["production_mutated"] is False
    assert report["provider_requests"] == 0
    assert "private-match-id" not in json.dumps(report)
    assert "private-event-id" not in json.dumps(report)


def test_identity_safety_aggregate_safe_case():
    from scripts.recover_cdb_opponent_service_rates import identity_safety_aggregate
    report = identity_safety_aggregate({
        "input_rows": 5, "rows_after_proven_merges": 5,
        "output_rows": 5, "changed": False, "quarantined_rows": 0,
    })
    assert report["status"] == "IDENTITY_SAFE"
    assert report["input_rows"] == 5
