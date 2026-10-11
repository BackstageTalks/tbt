"""Synthetic-only proof for strict, non-mutating Wimbledon 2023 recovery audit."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_wimbledon2023_recovery_readonly import TARGET_IDS, compare_years


def fixture_rows():
    players = [
        ("Ons Jabeur", "Elena Rybakina", "2023-07-12T12:00:00Z"),
        ("Madison Keys", "Aryna Sabalenka", "2023-07-12T12:30:00Z"),
        ("Ons Jabeur", "Aryna Sabalenka", "2023-07-13T12:30:00Z"),
        ("Elina Svitolina", "Marketa Vondrousova", "2023-07-13T14:15:00Z"),
        ("Marketa Vondrousova", "Ons Jabeur", "2023-07-15T13:00:00Z"),
    ]
    rows = []
    for mid, (p1, p2, when) in zip(sorted(TARGET_IDS), players):
        rows.append({
            "match_id": mid, "tour": "wta", "scheduled_at": when,
            "player1_id": "101", "player2_id": "202",
            "player1_name": p1, "player2_name": p2,
            "tournament": "Wimbledon",
            "winner_id": "101",
            "stats_json": json.dumps({"p1_break_points_won": 4,
                                      "p2_break_points_won": 0,
                                      "p1_aces": 5}),
        })
    rows.append({
        "match_id": "safe-other", "tour": "atp",
        "scheduled_at": "2023-07-12T12:00:00Z",
        "player1_id": "301", "player2_id": "302",
        "player1_name": "One", "player2_name": "Two",
        "tournament": "Other", "winner_id": "301",
        "stats_json": "{}",
    })
    return pd.DataFrame(rows)


def test_exact_five_only_are_restoration_review_candidates():
    backup = fixture_rows()
    current = backup.loc[backup["match_id"] == "safe-other"].copy()
    proof = compare_years(backup, current)
    assert proof["five_missing_in_current"] == 5
    assert proof["five_valid_under_canonical_2023_rule"] == 5
    assert proof["backup_absent_unrelated_to_five"] == 0
    assert proof["exact_five_can_be_reviewed_for_restoration"] is True
    assert len(backup) == 6 and len(current) == 1


def test_unauthorized_missing_row_blocks_exact_recovery():
    source = fixture_rows()
    now = source.loc[source["match_id"] == "safe-other"].copy()
    now = now.loc[now["match_id"] != "safe-other"]
    assert compare_years(source, now)["exact_five_can_be_reviewed_for_restoration"] is False
    assert compare_years(source, now)["backup_absent_unrelated_to_five"] == 1


def test_missing_target_in_immutable_backup_blocks_approval():
    source = fixture_rows()
    omitted = sorted(TARGET_IDS)[0]
    source = source.loc[source["match_id"] != omitted].copy()
    current = source.loc[source["match_id"] == "safe-other"].copy()
    proof = compare_years(source, current)
    assert proof["all_five_present_in_backup"] is False
    assert proof["exact_five_can_be_reviewed_for_restoration"] is False


def test_shared_identity_drift_blocks_approval():
    source = fixture_rows()
    current = source.loc[source["match_id"] == "safe-other"].copy()
    current["player1_id"] = "9999"
    proof = compare_years(source, current)
    assert proof["shared_identity_drift"] == 1
    assert proof["exact_five_can_be_reviewed_for_restoration"] is False


def test_duplicate_ids_are_rejected():
    source = fixture_rows()
    duplicate = pd.concat([source, source.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        compare_years(duplicate, source.iloc[[-1]].copy())


def test_source_count_rate_outside_pinned_pair_blocks_approval():
    source = fixture_rows()
    target = sorted(TARGET_IDS)[0]
    source.loc[source["match_id"] == target, "player1_name"] = "Wrong Name"
    current = source.loc[source["match_id"] == "safe-other"].copy()
    proof = compare_years(source, current)
    assert proof["five_failed_validation"] == 1
    assert proof["exact_five_can_be_reviewed_for_restoration"] is False



def test_local_append_preserves_every_current_value_and_deletes_staging(tmp_path):
    from audit_wimbledon2023_recovery_readonly import simulate_exact_five_append
    original = fixture_rows()
    current = original.loc[original["match_id"] == "safe-other"].copy()
    current["stats_json"] = '{"p1_aces": 999}'
    proof = simulate_exact_five_append(original, current, tmp_path)
    assert proof["current_rows_preserved_exact"] == 1
    assert proof["five_backup_rows_appended_exact"] == 5
    assert proof["simulated_total_rows"] == 6
    assert proof["existing_rows_or_cells_overwritten"] == 0
    assert proof["production_cdb_mutated"] is False
    assert len(proof["simulated_parquet_sha256"]) == 64
    assert not list(tmp_path.glob("**/*.parquet"))
    # Simulator must not mutate the input frames.
    assert current.iloc[0]["stats_json"] == '{"p1_aces": 999}'
    assert len(original) == 6


def test_local_append_blocks_incompatible_schema(tmp_path):
    from audit_wimbledon2023_recovery_readonly import simulate_exact_five_append
    original = fixture_rows()
    current = original.loc[original["match_id"] == "safe-other"].copy()
    original["invented_column"] = 1
    with pytest.raises(ValueError, match="column inventory differs"):
        simulate_exact_five_append(original, current, tmp_path)
    assert not list(tmp_path.glob("**/*.parquet"))


def test_local_append_fails_on_any_unrelated_missing_match(tmp_path):
    from audit_wimbledon2023_recovery_readonly import simulate_exact_five_append
    source = fixture_rows()
    current = source.iloc[0:0].copy()
    with pytest.raises(ValueError, match="must first pass"):
        simulate_exact_five_append(source, current, tmp_path)
    assert not list(tmp_path.glob("**/*.parquet"))


def test_local_append_blocks_invalid_one_of_five(tmp_path):
    from audit_wimbledon2023_recovery_readonly import simulate_exact_five_append
    source = fixture_rows()
    current = source.loc[source["match_id"] == "safe-other"].copy()
    source.loc[source["match_id"] == sorted(TARGET_IDS)[0], "stats_json"] = '{"p1_break_points_won": 500}'
    with pytest.raises(ValueError, match="must first pass"):
        simulate_exact_five_append(source, current, tmp_path)
    assert not list(tmp_path.glob("**/*.parquet"))
